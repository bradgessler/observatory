defmodule Mount.Discovery do
  @moduledoc """
  Keeps one `Mount.Server` per configured mount. With `mounts: :auto` it
  rescans the USB serial ports every few seconds, starting a driver when an
  EQDIR cable shows up and stopping it when the cable is pulled. With no
  cable at all in dev/test it starts a simulator so everything above still runs.
  """
  use GenServer
  require Logger

  @scan_ms 3_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_opts) do
    send(self(), :scan)
    {:ok, %{running: %{}}}
  end

  @impl true
  def handle_info(:scan, state) do
    wanted = Map.new(desired(), &{&1[:id], &1})

    for {id, _} <- state.running, not Map.has_key?(wanted, id) do
      Logger.info("mount #{id}: gone")
      DynamicSupervisor.terminate_child(Mount.Supervisor, state.running[id])
    end

    running =
      for {id, spec} <- wanted, into: %{} do
        case state.running[id] do
          nil ->
            {:ok, pid} = DynamicSupervisor.start_child(Mount.Supervisor, {Mount.Server, spec})
            Logger.info("mount #{id}: starting on #{inspect(spec[:transport])}")
            {id, pid}

          pid ->
            {id, pid}
        end
      end

    if Application.get_env(:mount, :mounts, :auto) == :auto,
      do: Process.send_after(self(), :scan, @scan_ms)

    {:noreply, %{state | running: running}}
  end

  defp desired do
    case Application.get_env(:mount, :mounts, :auto) do
      :auto ->
        case Mount.Transport.Serial.detect() do
          [] -> if Application.get_env(:mount, :simulate_when_empty, false), do: [sim()], else: []
          ports -> Enum.map(ports, &serial/1)
        end

      list when is_list(list) ->
        list
    end
  end

  defp serial(port),
    do: [id: Path.basename(port), transport: {Mount.Transport.Serial, port: port}]

  defp sim, do: [id: "sim", transport: {Mount.Transport.Sim, []}]
end
