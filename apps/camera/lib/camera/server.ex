defmodule Camera.Server do
  @moduledoc """
  One camera: connects, keeps its settings fresh, takes pictures on request.
  Its state is broadcast on `"camera:<id>"` and `"cameras"` (via
  `Telescope.broadcast/3`) whenever it changes, so every page shows the same
  camera: on every machine for a real one, on this machine only for the
  simulated one.

  A camera that stops answering ends this process (`{:shutdown, reason}`):
  `Camera.Discovery` notices, restarts it within its budget, and says in one
  line when it gives up. A failure here never reaches the mount.

  **The camera's clock** is set once a connection, from this machine's,
  when this machine's is trusted (set by the network: `Controller.Clock.synced?/0`
  when the controller runs here; `config :camera, clock: fun` stands in for
  it) and the camera offers its DateTime as settable (`Camera.Sony.set_clock/4`).
  Not yet trusted: asked again with each refresh. A camera that doesn't offer
  it, or refuses, is asked nothing more and its status says so (`clock`);
  the log says it once. `config :camera, set_clock: false` turns it off.

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
    # registered with whether it is simulated, so its status says so from the first moment
    name = {:via, Registry, {Camera.Registry, id, sim?(opts[:transport])}}
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  def child_spec(opts),
    do: %{
      id: {__MODULE__, opts[:id]},
      start: {__MODULE__, :start_link, [opts]},
      restart: :temporary
    }

  def via(id), do: {:via, Registry, {Camera.Registry, id}}

  @doc """
  What the camera is and what it's set to (never blocks on a busy camera). `sim` says whether it
  is the simulated one, in every state: starting, ready or failed.
  """
  def status(id) do
    case Registry.lookup(Camera.Registry, id) do
      [{pid, sim}] ->
        {__MODULE__, id}
        |> :persistent_term.get(%{id: id, state: :starting, pid: pid})
        |> Map.put(:sim, sim == true)

      [] ->
        nil
    end
  end

  # driven through the simulated a6000, not a camera on the USB bus
  defp sim?(transport), do: match?({Camera.Transport.Sim, _}, transport)

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
  `status/1`, asked afterwards, may already say something else. With `progress: {pid, tag}` the
  pid is sent `{:camera_progress, tag, %{stage: ...}}` as the capture goes: `:preparing`,
  `:exposing` (with `exposure_ms`), `:processing`, `:downloading` (with `file`, `name`, `bytes`).
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
       shots: 0,
       # setting the camera's clock: nil until it has been tried this connection, then what came of it
       clock: nil
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
      {:noreply, publish(clock(%{s | conn: conn, info: info, props: props}))}
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

    case Sony.capture(s.conn, exposure_ms: exposure, progress: opts[:progress]) do
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
        {:noreply, publish(clock(%{s | conn: conn, props: props}))}

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

  # -- the camera's clock ----------------------------------------------------------------------

  # Once a connection: set the camera's clock from this machine's, when this machine's is to be
  # trusted. Whatever the camera says, the camera carries on: this never ends the process.
  defp clock(%{clock: nil} = s) do
    cond do
      Application.get_env(:camera, :set_clock, true) == false ->
        %{s | clock: %{set: false, why: :turned_off}}

      not Sony.clock_offered?(s.info || %{}, s.props) ->
        said(s, %{set: false, why: :not_offered})

      true ->
        case trusted_now() do
          %DateTime{} = now ->
            case Sony.set_clock(s.conn, s.info || %{}, s.props, now) do
              {:ok, %{sent: sent, how: how}, conn} -> said(%{s | conn: conn}, %{set: true, sent: sent, how: how, at: now, zone: "UTC"})
              {:error, why, conn} -> said(%{s | conn: conn}, %{set: false, why: why})
            end

          # not yet: asked again at the next refresh
          _ ->
            s
        end
    end
  end

  defp clock(s), do: s

  # what came of it, kept, and said in the log once (a camera that reconnects all night says it once)
  defp said(s, result) do
    key = {__MODULE__, :clock_said, s.id, result[:set], result[:why]}

    unless :persistent_term.get(key, false) do
      :persistent_term.put(key, true)

      if result.set,
        do: Logger.info("camera #{s.id}: its clock set to #{result.sent} UTC"),
        else: Logger.info("camera #{s.id}: its clock was not set (#{inspect(result.why)}); its pictures keep the camera's own date")
    end

    %{s | clock: result}
  end

  # this machine's time, when the network set it; nil when it isn't to be trusted yet
  defp trusted_now do
    case Application.get_env(:camera, :clock) do
      fun when is_function(fun, 0) ->
        fun.()

      nil ->
        clock = Controller.Clock
        if Code.ensure_loaded?(clock) and function_exported?(clock, :synced?, 0) and apply(clock, :synced?, []) == true, do: DateTime.utc_now()

      _ ->
        nil
    end
  rescue
    _ -> nil
  catch
    _, _ -> nil
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

  # image quality: `:best` (what `Sony.best_quality/1` picks from what the camera offers), `:raw`, or a code
  defp set_one(conn, :quality, q) do
    with {:ok, props, conn} <- Sony.props(conn) do
      offered = case get_in(props, [Sony.prop(:quality), :form]) do {:enum, vals} -> vals; _ -> [] end
      value = case q do :best -> Sony.best_quality(offered); :raw -> 16; v when is_integer(v) -> v; _ -> nil end

      if value, do: Sony.put(conn, Sony.prop(:quality), value), else: {:error, {:no_such_quality, q}, conn}
    end
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
      # as the camera reports them (PTP device info); a serial of all zeros, as the a6000 sends, is no serial
      serial: s.info && serial(s.info[:serial_number]),
      firmware: s.info && blank(s.info[:device_version]),
      # whether its clock was set from this machine's this connection (`clock/1`), nil until tried
      clock: s.clock,
      device: s.device,
      # the simulated a6000 says so itself (Camera.simulated?/1)
      sim: sim?(s.transport),
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

  defp serial(v) when is_binary(v), do: if(String.trim(v, "0") == "", do: nil, else: blank(v))
  defp serial(_), do: nil

  defp blank(v) when is_binary(v), do: if(String.trim(v) == "", do: nil, else: String.trim(v))
  defp blank(_), do: nil

  # to every machine for a real camera; a simulated one is this machine's alone (Telescope.listed?/3)
  defp broadcast(id, st) do
    if Code.ensure_loaded?(Telescope) and function_exported?(Telescope, :broadcast, 3) do
      Telescope.broadcast("camera:" <> id, {:camera, st}, simulated: st.sim)
      Telescope.broadcast("cameras", {:camera, st}, simulated: st.sim)
    end
  catch
    _, _ -> :ok
  end
end
