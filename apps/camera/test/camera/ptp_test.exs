defmodule Camera.PtpTest do
  @moduledoc "PTP containers and datasets, checked against what a real a6000 sent."
  use ExUnit.Case, async: true
  alias Camera.Ptp

  defp fixture(name), do: File.read!(Path.join(:code.priv_dir(:camera), "sim/a6000/" <> name))

  test "a command container is little-endian: length, type, code, transaction, parameters" do
    assert Ptp.command(0x1002, 0, [1]) ==
             <<16::32-little, 1::16-little, 0x1002::16-little, 0::32-little, 1::32-little>>
  end

  test "a container that hasn't all arrived says how much more is needed" do
    bin = Ptp.container(:data, 0x1001, 1, String.duplicate("x", 100))
    assert {:more, 50} = Ptp.parse(binary_part(bin, 0, 62))
    assert {:ok, %{type: :data, code: 0x1001, tid: 1, payload: p}, ""} = Ptp.parse(bin)
    assert byte_size(p) == 100
  end

  test "the a6000's device info reads as itself (its serial number blanked in the recording)" do
    {:ok, %{type: :data, payload: payload}, ""} = Ptp.parse(fixture("device_info.bin"))
    info = Ptp.device_info(payload)
    assert info.manufacturer == "Sony Corporation"
    assert info.model == "ILCE-6000"
    assert info.serial_number =~ ~r/^0+$/
    assert 0x9201 in info.operations
  end

  test "strings go both ways" do
    for s <- ["", "DSC01234.JPG", "Sony Corporation"] do
      assert {^s, "rest"} = Ptp.string(Ptp.encode_string(s) <> "rest")
    end
  end

  test "object info goes both ways" do
    info = %{
      storage_id: 0x00010001,
      format: :jpeg,
      size: 4_940_245,
      width: 6000,
      height: 4000,
      filename: "DSC00256.JPG",
      capture_date: "20261003T080614"
    }

    back = Ptp.object_info(Ptp.encode_object_info(info))

    assert back.filename == "DSC00256.JPG" and back.format == :jpeg and back.size == 4_940_245 and
             back.width == 6000
  end

  test "values of every type go both ways" do
    for {t, v} <- [
          int8: -3,
          uint8: 250,
          int16: -1000,
          uint16: 0x8001,
          int32: -70000,
          uint32: 0xFFFFFF,
          string: "hi"
        ] do
      assert {^v, ""} = Ptp.value(t, Ptp.encode_value(t, v))
    end
  end
end
