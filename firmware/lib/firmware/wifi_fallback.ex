defmodule Firmware.WifiFallback do
  @moduledoc """
  If Wi-Fi hasn't come up within `:wizard_after_ms` (new site, changed
  password, no network baked in), start VintageNetWizard: the Pi becomes the
  `telescope-setup` access point and serves a page at http://telescope.setup
  to pick a network. The choice is saved, the AP goes away, normal life resumes.

  Ethernet or the USB link being up is enough to skip this — you can add
  Wi-Fi from a shell in that case.
  """
  use GenServer
  require Logger

  @compile {:no_warn_undefined, [VintageNet, VintageNetWizard]}

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_) do
    Process.send_after(self(), :check, Application.get_env(:firmware, :wizard_after_ms, 60_000))
    {:ok, %{}}
  end

  @impl true
  def handle_info(:check, state) do
    cond do
      connected?("wlan0") or connected?("eth0") or connected?("usb0") ->
        :ok

      true ->
        Logger.warning("no network after timeout; starting Wi-Fi setup hotspot")
        VintageNetWizard.run_wizard(on_exit: {Logger, :info, ["Wi-Fi setup finished"]})
    end

    {:noreply, state}
  end

  defp connected?(ifname) do
    VintageNet.get(["interface", ifname, "connection"]) in [:lan, :internet]
  end
end
