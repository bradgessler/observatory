defmodule Firmware.Bluetooth.RadioTest do
  use ExUnit.Case, async: true

  alias Firmware.Bluetooth.Radio

  @adapter %{address: "B8:27:EB:8C:33:A6", name: "BlueZ 5.79", path: "/org/bluez/hci0", powered: true}

  defp look(hci, adapters), do: %{hci: hci, adapters: adapters, mode: :passive}

  test "an adapter in BlueZ is up, however long it took" do
    assert {:up, _} = Radio.decide(Radio.new(0), look(true, [@adapter]), 5_000)
    assert {:up, _} = Radio.decide(Radio.new(0), look(true, [@adapter]), 500_000)
  end

  # the Pi 3 at power-on: hci0 made at 1.5 s, its setup lost, BlueZ empty
  test "hci0 with no adapter is given 20 s, then its driver is reattached" do
    radio = Radio.new(0)
    assert {:wait, radio} = Radio.decide(radio, look(true, []), 10_000)
    assert {:wait, radio} = Radio.decide(radio, look(true, []), 19_999)
    assert {:reattach, radio} = Radio.decide(radio, look(true, []), 20_000)
    assert radio.resets == 1

    # a fresh 20 s after each reattach, not a reattach on every look
    assert {:wait, _} = Radio.decide(radio, look(true, []), 25_000)
    assert {:up, radio} = Radio.decide(radio, look(true, [@adapter]), 30_000)
    assert radio.resets == 1
  end

  test "after three reattaches that do not bring it up, it gives up" do
    radio =
      Enum.reduce(1..3, Radio.new(0), fn n, radio ->
        assert {:reattach, radio} = Radio.decide(radio, look(true, []), n * 20_000)
        radio
      end)

    assert radio.resets == 3
    assert {:failed, _} = Radio.decide(radio, look(true, []), 80_000)
  end

  test "no hci at all for 30 s is a board without a radio, not a failure" do
    radio = Radio.new(0)
    assert {:wait, radio} = Radio.decide(radio, look(false, []), 20_000)
    assert {:no_radio, radio} = Radio.decide(radio, look(false, []), 30_000)
    assert radio.resets == 0
  end

  test "the stack starting again restarts the grace period, keeping the count" do
    radio = %{Radio.new(0) | resets: 2}
    radio = Radio.started(radio, 100_000)
    assert {:wait, _} = Radio.decide(radio, look(true, []), 110_000)
    assert radio.resets == 2
  end

  describe "reattaching a driver" do
    # sysfs as a Pi 3 has it: every hop a relative symlink, read from where
    # the one before it landed
    setup do
      root = Path.join(System.tmp_dir!(), "bt-sys-#{System.unique_integer([:positive])}")
      File.mkdir_p!(root)
      on_exit(fn -> File.rm_rf!(root) end)
      # the temp dir can be a link itself (macOS: /var -> /private/var)
      {:ok, root} = Firmware.Bluetooth.realpath(root)

      device = Path.join(root, "devices/platform/soc/3f215040.serial/3f215040.serial:0/3f215040.serial:0.0/serial0/serial0-0")
      driver = Path.join(root, "bus/serial/drivers/hci_uart_bcm")
      File.mkdir_p!(Path.join(device, "bluetooth/hci0"))
      File.mkdir_p!(driver)
      File.mkdir_p!(Path.join(root, "class/bluetooth"))

      File.ln_s!(
        "../../devices/platform/soc/3f215040.serial/3f215040.serial:0/3f215040.serial:0.0/serial0/serial0-0/bluetooth/hci0",
        Path.join(root, "class/bluetooth/hci0")
      )

      File.ln_s!("../../../serial0-0", Path.join(device, "bluetooth/hci0/device"))
      File.ln_s!("../../../../../../../../bus/serial/drivers/hci_uart_bcm", Path.join(device, "driver"))
      %{root: root, device: device, driver: driver}
    end

    test "resolves the links the way the kernel lays them out", %{root: root, device: device, driver: driver} do
      assert {:ok, ^device} = Firmware.Bluetooth.realpath(Path.join(root, "class/bluetooth/hci0/device"))
      assert {:ok, ^driver} = Firmware.Bluetooth.realpath(Path.join(root, "class/bluetooth/hci0/device/driver"))
    end

    test "unbinds and binds the device behind hci0 on its own driver", %{root: root, driver: driver} do
      assert [{"serial0-0", :ok, :ok}] = Firmware.Bluetooth.reattach_driver(root)
      assert File.read!(Path.join(driver, "unbind")) == "serial0-0"
      assert File.read!(Path.join(driver, "bind")) == "serial0-0"
    end

    test "a radio with no driver, or no radio, is nothing to do", %{root: root, device: device} do
      File.rm!(Path.join(device, "driver"))
      assert Firmware.Bluetooth.reattach_driver(root) == []
      assert Firmware.Bluetooth.reattach_driver(Path.join(root, "nowhere")) == []
    end

    test "a link loop is an error, not a hang", %{root: root} do
      File.ln_s!("b", Path.join(root, "a"))
      File.ln_s!("a", Path.join(root, "b"))
      assert {:error, :eloop} = Firmware.Bluetooth.realpath(Path.join(root, "a"))
    end
  end

  describe "a system without BlueZ" do
    test "reports Bluetooth unavailable and answers every call" do
      start_supervised!({Firmware.Bluetooth, []})
      Process.sleep(50)

      assert %{state: :unavailable, adapter: nil, resets: 0} = Firmware.Bluetooth.status()
      assert Firmware.Bluetooth.active_scan() == {:error, :not_running}
    end

    test "answers even when it is not running at all" do
      assert %{state: :not_running} = Firmware.Bluetooth.status()
      assert Firmware.Bluetooth.restart() == {:error, :not_running}
    end
  end
end
