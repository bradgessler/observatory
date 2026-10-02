defmodule Input.Discovery do
  @moduledoc """
  Every few seconds, list HID devices and keep an `Input.Device` open for each
  joystick/gamepad (usage page 1, usage 4 or 5). Plug one in and it appears
  within 3 s; pull it and its process ends. On Linux (a box) the kernel's
  hidraw devices are read directly (`Input.HIDRaw`); elsewhere through the C
  helper (`Input.HIDPort`).
  """
  use GenServer
  require Logger

  @scan_ms 3_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def scan, do: GenServer.call(__MODULE__, :scan)

  @doc "Last enumeration, all HID devices, with whether we're reading each."
  def seen, do: GenServer.call(__MODULE__, :seen)

  @impl true
  def init(_) do
    # `config :input, discover: false` (tests) leaves devices alone
    if Application.get_env(:input, :discover, true), do: send(self(), :scan)
    {:ok, %{seen: [], last_scan: nil}}
  end

  @impl true
  def handle_info(:scan, state) do
    state = do_scan(state)
    Process.send_after(self(), :scan, @scan_ms)
    {:noreply, state}
  end

  @impl true
  def handle_call(:scan, _from, state), do: {:reply, :ok, do_scan(state)}
  def handle_call(:seen, _from, state), do: {:reply, %{devices: state.seen, last_scan: state.last_scan}, state}

  defp do_scan(state) do
    devices = if Input.HIDRaw.available?(), do: Input.HIDRaw.list(), else: Input.HIDPort.list()

    for dev <- devices, gamepad?(dev), not running?(dev) do
      case DynamicSupervisor.start_child(Input.DeviceSupervisor, {Input.Device, dev}) do
        {:ok, _} -> Logger.info("input: opening #{dev.product} (#{Input.Device.id_of(dev)})")
        {:error, {:already_started, _}} -> :ok
        {:error, reason} -> Logger.warning("input: could not open #{dev.product}: #{inspect(reason)}")
      end
    end

    seen = Enum.map(devices, &Map.put(&1, :reading, running?(&1)))
    %{state | seen: seen, last_scan: DateTime.utc_now()}
  end

  defp gamepad?(%{usage_page: 1, usage: u}) when u in [4, 5], do: true
  defp gamepad?(_), do: false

  defp running?(dev), do: Registry.lookup(Input.Registry, Input.Device.id_of(dev)) != []
end
