defmodule Firmware do
  @moduledoc """
  Handy calls from an ssh shell on the Pi (`ssh telescope.local`).

      Firmware.status()                 # network + mounts at a glance
      Firmware.add_wifi("Site", "pw")   # remember another network, persisted
  """

  # VintageNet only exists on the device; keep the host build warning-free.
  @compile {:no_warn_undefined, [VintageNet, VintageNetWizard]}

  @doc "Add a Wi-Fi network alongside the ones already known. Persists across reboots."
  def add_wifi(ssid, psk) do
    current = VintageNet.get_configuration("wlan0")
    known = get_in(current, [:vintage_net_wifi, :networks]) || []
    new = %{key_mgmt: :wpa_psk, ssid: ssid, psk: psk}
    networks = Enum.reject(known, &(&1.ssid == ssid)) ++ [new]

    VintageNet.configure("wlan0", %{
      type: VintageNetWiFi,
      vintage_net_wifi: %{networks: networks},
      ipv4: %{method: :dhcp}
    })
  end

  def status do
    %{
      node: node(),
      interfaces:
        for ifname <- VintageNet.all_interfaces(), into: %{} do
          {ifname,
           %{
             connection: VintageNet.get(["interface", ifname, "connection"]),
             addresses:
               (VintageNet.get(["interface", ifname, "addresses"]) || [])
               |> Enum.map(&:inet.ntoa(&1.address))
               |> Enum.map(&to_string/1)
           }}
        end,
      mounts: Mount.list() |> Enum.map(&Mount.snapshot/1)
    }
  end
end
