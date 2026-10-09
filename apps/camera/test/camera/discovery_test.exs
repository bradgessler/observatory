defmodule Camera.DiscoveryTest do
  @moduledoc "Finding cameras on Linux's USB bus, and noticing the one that came up as a disk."
  use ExUnit.Case, async: true

  defp device(root, name, files) do
    for {path, value} <- files do
      full = Path.join([root, name, path])
      File.mkdir_p!(Path.dirname(full))
      File.write!(full, value <> "\n")
    end
  end

  setup do
    root = Path.join(System.tmp_dir!(), "sysfs-#{System.unique_integer([:positive])}")
    on_exit(fn -> File.rm_rf!(root) end)
    %{root: root}
  end

  test "a camera in PC Remote mode is one to drive; one in storage mode gets a line saying how to fix it",
       %{root: root} do
    device(root, "1-1.2", %{
      "idVendor" => "054c",
      "idProduct" => "094e",
      "manufacturer" => "Sony",
      "product" => "ILCE-6000",
      "busnum" => "1",
      "devnum" => "40"
    })

    File.mkdir_p!(Path.join(root, "1-1.2:1.0"))
    File.write!(Path.join([root, "1-1.2:1.0", "bInterfaceClass"]), "06\n")

    device(root, "1-1.3", %{
      "idVendor" => "054c",
      "idProduct" => "07c3",
      "manufacturer" => "Sony",
      "product" => "ILCE-6000",
      "busnum" => "1",
      "devnum" => "41"
    })

    File.mkdir_p!(Path.join(root, "1-1.3:1.0"))
    File.write!(Path.join([root, "1-1.3:1.0", "bInterfaceClass"]), "08\n")

    device(root, "1-1.4", %{
      "idVendor" => "045e",
      "idProduct" => "0028",
      "product" => "SideWinder Dual Strike",
      "busnum" => "1",
      "devnum" => "5"
    })

    [ptp, disk] = Camera.Discovery.linux_cameras(root) |> Enum.sort_by(& &1.mode)

    assert ptp.mode == :ptp and ptp.device == "/dev/bus/usb/001/040" and
             ptp.id == "sony-ilce-6000"

    assert disk.mode == :storage
  end
end
