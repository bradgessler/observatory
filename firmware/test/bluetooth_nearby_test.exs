defmodule Firmware.Bluetooth.NearbyTest do
  use ExUnit.Case, async: false

  alias Firmware.Bluetooth.Nearby

  # flags, then a complete local name, then manufacturer data for company
  # 0x0A9C with three bytes, then a 16-bit service UUID list and service data
  @advert <<2, 0x01, 0x06>> <>
            <<17, 0x09, "Anker SOLIX C200">> <>
            <<6, 0xFF, 0x9C, 0x0A, 0x01, 0x02, 0x03>> <>
            <<5, 0x03, 0x0F, 0x18, 0x0A, 0x18>> <>
            <<4, 0x16, 0x0F, 0x18, 0x55>>

  test "reads the name, services and data a device broadcasts" do
    assert Nearby.parse_ad(@advert) == %{
             name: "Anker SOLIX C200",
             manufacturer: %{"0A9C" => "010203"},
             uuids: ["180F", "180A"],
             service: %{"180F" => "55"}
           }
  end

  test "stops at a truncated or zero-length field instead of raising" do
    assert Nearby.parse_ad(<<17, 0x09, "short">>) == %{}
    assert Nearby.parse_ad(<<0, 0x09>>) == %{}
    assert Nearby.parse_ad(<<>>) == %{}
  end

  describe "the table" do
    setup do
      pid = start_supervised!(Nearby)
      %{pid: pid}
    end

    test "lists devices strongest first, with the MAC spelled out", %{pid: pid} do
      Nearby.heard(%{address: 0xAABBCCDDEEFF, rss: -80, address_type: 0, raw_data: <<>>})
      Nearby.heard(%{address: 0x0000000000A1, rss: -50, address_type: 1, raw_data: @advert})
      :sys.get_state(pid)

      assert [near, far] = Nearby.list()
      assert near.name == "Anker SOLIX C200"
      assert near.address == "00:00:00:00:00:A1"
      assert near.random
      assert far.address == "AA:BB:CC:DD:EE:FF"
      assert far.name == nil
    end

    test "keeps a name heard once when later adverts leave it out", %{pid: pid} do
      Nearby.heard(%{address: 1, rss: -60, address_type: 0, raw_data: @advert})
      Nearby.heard(%{address: 1, rss: -70, address_type: 0, raw_data: <<2, 0x01, 0x06>>})
      :sys.get_state(pid)

      assert [%{name: "Anker SOLIX C200", rssi: -70}] = Nearby.list()
    end

    test "shrugs off an advert it does not understand", %{pid: pid} do
      GenServer.cast(Nearby, {:heard, :garbage, 0})
      Nearby.heard(%{address: 2, rss: -40, address_type: 0, raw_data: <<255, 1>>})
      :sys.get_state(pid)

      assert [%{address: "00:00:00:00:00:02"}] = Nearby.list()
      assert Process.alive?(pid)
    end
  end

  test "an empty list, not a crash, when the table is not running" do
    assert Nearby.list() == []
  end
end
