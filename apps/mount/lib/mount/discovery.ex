defmodule Mount.Discovery do
  @moduledoc """
  Keeps one `Mount.Server` per mount. With `mounts: :auto` it rescans the USB
  serial ports every few seconds, starting a driver when an EQDIR cable shows
  up and stopping it when the cable is pulled. Ports can also be added by
  hand (a cable the auto-detector doesn't recognize) and a scan can be forced
  from the UI. With no cable at all in dev/test it starts a simulator.
  """
  use GenServer
  require Logger

  @scan_ms 3_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Rescan right now (the periodic scan keeps running too)."
  def scan, do: GenServer.call(__MODULE__, :scan)

  @doc "Start a driver on a specific serial port, whatever it looks like."
  def add_port(port), do: GenServer.call(__MODULE__, {:add_port, port})

  @doc "Stop a driver started by hand (auto-detected ones come back on the next scan)."
  def remove_port(port), do: GenServer.call(__MODULE__, {:remove_port, port})

  @doc """
  Run a simulated mount beside whatever is plugged in (`true`), or stop it.
  For a box whose mount is switched off: the pages keep working against a
  simulator (id `"sim-eq"`) until the real one answers. Not kept across a
  restart.
  """
  def simulator(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:simulator, on?})

  @doc "Is a simulator running because someone asked for one?"
  def simulator?, do: GenServer.call(__MODULE__, :simulator?)

  @doc "Everything the OS lists as a serial port, with what we make of it."
  def ports do
    running = running_ports()

    Circuits.UART.enumerate()
    |> Enum.reject(fn {name, _} -> String.starts_with?(name, "tty.") end)
    |> Enum.map(fn {name, info} ->
      path = Mount.Transport.Serial.device_path(name)

      %{
        path: path,
        description: info[:description],
        manufacturer: info[:manufacturer],
        vendor_id: info[:vendor_id],
        product_id: info[:product_id],
        serial_number: info[:serial_number],
        looks_like_mount: info[:vendor_id] == 0x0403,
        mount_id: running[path]
      }
    end)
    |> Enum.sort_by(&{not &1.looks_like_mount, &1.path})
  end

  @doc "When the last scan ran and what it found."
  def status, do: GenServer.call(__MODULE__, :status)

  # -- server -------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    send(self(), :scan)
    {:ok, %{running: %{}, manual: [], last_scan: nil, sim: false}}
  end

  @impl true
  def handle_info(:scan, state) do
    state = do_scan(state)
    if auto?(), do: Process.send_after(self(), :scan, @scan_ms)
    {:noreply, state}
  end

  @impl true
  def handle_call(:scan, _from, state), do: {:reply, :ok, do_scan(state)}

  def handle_call({:add_port, port}, _from, state) do
    state = %{state | manual: Enum.uniq([port | state.manual])} |> do_scan()
    {:reply, :ok, state}
  end

  def handle_call({:remove_port, port}, _from, state) do
    state = %{state | manual: List.delete(state.manual, port)} |> do_scan()
    {:reply, :ok, state}
  end

  def handle_call({:simulator, on?}, _from, state), do: {:reply, :ok, do_scan(%{state | sim: on?})}
  def handle_call(:simulator?, _from, state), do: {:reply, state.sim, state}

  def handle_call(:status, _from, state) do
    {:reply, %{last_scan: state.last_scan, manual: state.manual, running: Map.keys(state.running)}, state}
  end

  defp do_scan(state) do
    wanted = Map.new(desired(state.manual, state.sim), &{&1[:id], &1})

    for {id, pid} <- state.running, not Map.has_key?(wanted, id) do
      Logger.info("mount #{id}: gone")
      DynamicSupervisor.terminate_child(Mount.Supervisor, pid)
    end

    running =
      for {id, spec} <- wanted, into: %{} do
        case state.running[id] do
          nil ->
            Logger.info("mount #{id}: starting on #{inspect(spec[:transport])}")

            case DynamicSupervisor.start_child(Mount.Supervisor, {Mount.Server, spec}) do
              {:ok, pid} -> {id, pid}
              {:error, {:already_started, pid}} -> {id, pid}
              {:error, reason} ->
                Logger.error("mount #{id}: could not start: #{inspect(reason)}")
                {id, nil}
            end

          pid ->
            {id, pid}
        end
      end
      |> Map.reject(fn {_, pid} -> is_nil(pid) end)

    %{state | running: running, last_scan: DateTime.utc_now()}
  end

  defp auto?, do: Application.get_env(:mount, :mounts, :auto) == :auto

  defp desired(manual, sim?) do
    configured =
      case Application.get_env(:mount, :mounts, :auto) do
        :auto -> Enum.map(Mount.Transport.Serial.detect(), &serial/1)
        list when is_list(list) -> list
      end

    by_hand = Enum.map(manual, &serial/1)
    all = Enum.uniq_by(configured ++ by_hand, & &1[:id])

    cond do
      sim? -> Enum.uniq_by(all ++ [sim()], & &1[:id])
      all == [] and Application.get_env(:mount, :simulate_when_empty, false) -> [sim()]
      true -> all
    end
  end

  defp running_ports do
    Registry.select(Mount.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Map.new(fn id -> {port_for(id), id} end)
  end

  # ids are the port basename; map back to the path we'd have used
  defp port_for(id), do: Mount.Transport.Serial.device_path(id)

  defp serial(port),
    do: [id: Path.basename(port), transport: {Mount.Transport.Serial, port: port}]

  defp sim, do: [id: "sim-eq", transport: {Mount.Transport.Sim, []}]
end
