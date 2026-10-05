defmodule Camera.Server do
  @moduledoc """
  One camera: connects, keeps its settings fresh, takes pictures on request.
  Its state is broadcast on `"camera:<id>"` and `"cameras"` (via
  `Telescope.broadcast/2`) whenever it changes, so every page shows the same
  camera.

  A camera that stops answering ends this process (`{:shutdown, reason}`):
  `Camera.Discovery` notices, restarts it within its budget, and says in one
  line when it gives up. A failure here never reaches the mount.

      Camera.Server.status("ilce-6000")
      Camera.Server.set("ilce-6000", iso: 800, shutter: "1/60")
      {:ok, files} = Camera.Server.capture("ilce-6000")
  """
  use GenServer
  require Logger

  alias Camera.{Ptp, Sony}

  @refresh_ms 5_000

  def start_link(opts) do
    id = Keyword.fetch!(opts, :id)
    GenServer.start_link(__MODULE__, opts, name: via(id))
  end

  def child_spec(opts),
    do: %{
      id: {__MODULE__, opts[:id]},
      start: {__MODULE__, :start_link, [opts]},
      restart: :temporary
    }

  def via(id), do: {:via, Registry, {Camera.Registry, id}}

  @doc "What the camera is and what it's set to (never blocks on a busy camera)."
  def status(id) do
    case Registry.lookup(Camera.Registry, id) do
      [{pid, _}] -> :persistent_term.get({__MODULE__, id}, %{id: id, state: :starting, pid: pid})
      [] -> nil
    end
  end

  @doc """
  Change settings: `iso:` (a number or `:auto`), `shutter:` (`"1/200"`, `"1"`,
  `"2.5"`, `"Bulb"`, or seconds). The camera's dials are turned until they
  read the value, or the nearest it offers. Returns the new status.
  """
  def set(id, settings, timeout \\ 120_000),
    do: GenServer.call(via(id), {:set, settings}, timeout)

  @doc """
  Take one picture: `{:ok, [%{name, format, bytes, info, pressed_at, ready_at, settings}]}` (two
  files for RAW+JPEG). `settings` is what the camera was set to when the shutter was pressed;
  `status/1`, asked afterwards, may already say something else.
  """
  def capture(id, opts \\ []) do
    exposure = Keyword.get(opts, :exposure_ms, 0)
    GenServer.call(via(id), {:capture, opts}, exposure + 120_000)
  end

  # -- the process -------------------------------------------------------------------------------

  @impl true
  def init(opts) do
    Process.flag(:trap_exit, true)

    {:ok,
     %{
       id: opts[:id],
       transport: opts[:transport],
       device: opts[:device],
       conn: nil,
       info: nil,
       props: %{},
       last: nil,
       shots: 0
     }, {:continue, :connect}}
  end

  @impl true
  def handle_continue(:connect, s) do
    {mod, topts} = s.transport

    with {:ok, ts} <- mod.open(topts),
         conn = %Ptp.Conn{transport: mod, state: ts},
         {:ok, info, conn} <- Sony.connect(conn),
         {:ok, props, conn} <- Sony.props(conn) do
      Process.send_after(self(), :refresh, @refresh_ms)
      {:noreply, publish(%{s | conn: conn, info: info, props: props})}
    else
      {:error, reason} -> stop(s, reason)
      {:error, reason, conn} -> stop(%{s | conn: conn}, reason)
    end
  end

  @impl true
  def handle_call({:set, settings}, _from, s) do
    result =
      Enum.reduce_while(settings, {:ok, s.conn}, fn {k, v}, {:ok, conn} ->
        case set_one(conn, k, v) do
          {:ok, _, conn} -> {:cont, {:ok, conn}}
          {:error, reason, conn} -> {:halt, {:error, reason, conn}}
        end
      end)

    case result do
      {:ok, conn} ->
        {:ok, props, conn} = Sony.props(conn)
        s = publish(%{s | conn: conn, props: props})
        {:reply, {:ok, status(s.id)}, s}

      {:error, reason, conn} ->
        failed(%{s | conn: conn}, reason)
    end
  end

  def handle_call({:capture, opts}, _from, s) do
    exposure = Keyword.get_lazy(opts, :exposure_ms, fn -> exposure_ms(s.props) end)
    t0 = System.monotonic_time(:millisecond)

    case Sony.capture(s.conn, exposure_ms: exposure) do
      {:ok, files, conn} ->
        last = %{
          at: DateTime.utc_now(),
          took_ms: System.monotonic_time(:millisecond) - t0,
          files:
            Enum.map(files, &Map.take(&1, [:name, :format]))
            |> Enum.map(&Map.put(&1, :bytes, nil))
        }

        last = %{
          last
          | files:
              Enum.zip_with(last.files, files, fn l, f -> %{l | bytes: byte_size(f.bytes)} end)
        }

        s = publish(%{s | conn: conn, last: last, shots: s.shots + 1})
        {:reply, {:ok, files}, s}

      {:error, reason, conn} ->
        failed(%{s | conn: conn}, reason)
    end
  end

  @impl true
  def handle_info(:refresh, s) do
    case Sony.props(s.conn) do
      {:ok, props, conn} ->
        Process.send_after(self(), :refresh, @refresh_ms)
        {:noreply, publish(%{s | conn: conn, props: props})}

      {:error, reason, conn} ->
        stop(%{s | conn: conn}, reason)
    end
  end

  def handle_info(_, s), do: {:noreply, s}

  @impl true
  def terminate(_reason, %{conn: %Ptp.Conn{} = conn}) do
    # give the camera back its own controls, then let go of the USB
    try do
      Sony.disconnect(conn)
      conn.transport.close(conn.state)
    catch
      _, _ -> :ok
    end

    :ok
  end

  def terminate(_, _), do: :ok

  # a call that failed ends the camera's process after answering: the next start is clean
  defp failed(s, reason) do
    publish(%{s | last: Map.put(s.last || %{}, :error, reason)})
    {:stop, {:shutdown, reason}, {:error, reason}, s}
  end

  defp stop(s, reason) do
    Logger.warning("camera #{s.id}: #{inspect(reason)}")
    :persistent_term.put({__MODULE__, s.id}, %{id: s.id, state: :failed, error: reason})
    {:stop, {:shutdown, reason}, s}
  end

  defp set_one(conn, :iso, :auto), do: Sony.set(conn, Sony.prop(:iso), 0xFFFFFF)
  defp set_one(conn, :iso, v) when is_integer(v), do: Sony.set(conn, Sony.prop(:iso), v)

  defp set_one(conn, :shutter, v) do
    order = fn x ->
      case Sony.shutter_seconds(x) do
        :bulb -> -1.0e6
        sec -> -sec
      end
    end

    Sony.set(conn, Sony.prop(:shutter), Sony.shutter_value(v), order: order)
  end

  defp set_one(conn, k, _v), do: {:error, {:unknown_setting, k}, conn}

  defp exposure_ms(props) do
    case Sony.shutter_seconds(get_in(props, [Sony.prop(:shutter), :current]) || 0) do
      :bulb -> 30_000
      sec -> round(sec * 1000)
    end
  end

  defp publish(s) do
    st = %{
      id: s.id,
      state: :ready,
      model: s.info && s.info.model,
      manufacturer: s.info && s.info.manufacturer,
      device: s.device,
      settings: Sony.describe(s.props),
      last: s.last,
      shots: s.shots
    }

    old = :persistent_term.get({__MODULE__, s.id}, nil)

    if old != st do
      :persistent_term.put({__MODULE__, s.id}, st)
      broadcast(s.id, st)
    end

    s
  end

  defp broadcast(id, st) do
    if Code.ensure_loaded?(Telescope) and function_exported?(Telescope, :broadcast, 2) do
      Telescope.broadcast("camera:" <> id, {:camera, st})
      Telescope.broadcast("cameras", {:camera, st})
    end
  catch
    _, _ -> :ok
  end
end
