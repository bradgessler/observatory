defmodule Input.Device do
  @moduledoc """
  One open HID device. Owns the port process, parses every report, keeps the
  latest state, and broadcasts `{:input, id, state}` on `"input"` (and on
  `"input:<id>"`) whenever the state changes. Dies with the device; Discovery
  starts it again when the device is back.
  """
  use GenServer
  require Logger

  alias Input.HIDPort

  def start_link(dev), do: GenServer.start_link(__MODULE__, dev, name: via(id_of(dev)))

  def via(id), do: {:via, Registry, {Input.Registry, id}}

  def child_spec(dev), do: %{id: {__MODULE__, id_of(dev)}, start: {__MODULE__, :start_link, [dev]}, restart: :transient}

  @doc "Stable id from vendor/product/path: `045e:0028@<path hash>`."
  def id_of(%{vendor_id: v, product_id: p, path: path}) do
    :io_lib.format("~4.16.0b:~4.16.0b@~s", [v, p, path |> :erlang.phash2() |> Integer.to_string(36)]) |> to_string()
  end

  def state(id), do: GenServer.call(via(id), :state)

  @impl true
  def init(dev) do
    Process.flag(:trap_exit, true)
    parser = Input.Parsers.for(dev)
    # hidraw on Linux (a Pi has no libhidapi), the C helper elsewhere; both
    # speak the same messages, so nothing below cares which
    port = if String.starts_with?(dev.path, "/dev/hidraw"), do: Input.HIDRaw.open(dev.path), else: HIDPort.open(dev.path)
    # The pad only reports on change. A steady hold must still read as fresh
    # intent, so re-publish the current state on a heartbeat.
    :timer.send_interval(200, :heartbeat)

    {:ok,
     %{
       id: id_of(dev),
       dev: dev,
       parser: parser,
       port: port,
       state: %{axes: [], buttons: [], hat: nil, extra: %{}, raw: <<>>},
       reports: 0,
       opened: false
     }}
  end

  @impl true
  def handle_call(:state, _from, s), do: {:reply, info(s), s}

  @impl true
  def handle_info({port, {:data, {:eol, "O " <> _}}}, %{port: port} = s) do
    Logger.info("input #{s.id}: #{s.parser.name()} open (#{s.dev.product})")
    {:noreply, broadcast(%{s | opened: true})}
  end

  def handle_info({port, {:data, {:eol, "R " <> hex}}}, %{port: port} = s) do
    report = Base.decode16!(hex, case: :lower)
    state = s.parser.parse(report)
    s = %{s | reports: s.reports + 1}

    if state == s.state, do: {:noreply, s}, else: {:noreply, broadcast(%{s | state: state})}
  end

  def handle_info({port, {:data, {:eol, "E " <> why}}}, %{port: port} = s) do
    Logger.warning("input #{s.id}: #{why}")
    {:stop, :normal, s}
  end

  def handle_info({port, {:exit_status, code}}, %{port: port} = s) do
    Logger.info("input #{s.id}: device gone (hidport exit #{code})")
    Telescope.local_broadcast("input", {:input_gone, s.id})
    {:stop, :normal, %{s | port: nil}}
  end

  # steady hold = fresh intent: re-publish the current state while the device is open
  def handle_info(:heartbeat, %{opened: true} = s), do: {:noreply, broadcast(s)}
  def handle_info(:heartbeat, s), do: {:noreply, s}

  def handle_info(_other, s), do: {:noreply, s}

  @impl true
  def terminate(_reason, %{port: port}) when is_port(port) do
    Port.close(port)
  catch
    _, _ -> :ok
  end

  def terminate(_reason, %{port: reader}) when is_pid(reader) do
    Process.unlink(reader)
    Process.exit(reader, :kill)
    :ok
  end

  def terminate(_reason, _s), do: :ok

  # `at` is monotonic ms: consumers must ignore stale states (a backlog of
  # old "trigger held" reports once moved the scope after the hand let go).
  defp info(s),
    do: %{
      id: s.id,
      device: s.dev,
      parser: s.parser.name(),
      parser_mod: s.parser,
      state: s.state,
      reports: s.reports,
      node: node(),
      at: System.monotonic_time(:millisecond)
    }

  defp broadcast(s) do
    msg = {:input, s.id, info(s)}
    Telescope.local_broadcast("input", msg)
    Telescope.local_broadcast("input:#{s.id}", msg)
    s
  end
end
