defmodule Camera.SonyTest do
  @moduledoc """
  Sony's PC Remote protocol against the simulated a6000 (which answers with a
  real a6000's bytes): the property blob, the handshake, turning dials a
  notch at a time, and pressing the shutter.
  """
  use ExUnit.Case, async: true
  alias Camera.{Ptp, Sony}
  alias Camera.Transport.Sim

  defp fixture(name), do: File.read!(Path.join(:code.priv_dir(:camera), "sim/a6000/" <> name))

  defp conn(opts \\ []) do
    {:ok, st} = Sim.open(opts)
    %Ptp.Conn{transport: Sim, state: st}
  end

  test "the a6000's property blob reads, and writes back byte for byte" do
    {:ok, %{payload: blob}, ""} = Ptp.parse(fixture("all_props_iso6400.bin"))
    props = Sony.parse_props(blob)
    assert map_size(props) == 34
    assert Sony.encode_props(props) == blob

    s = Sony.describe(props)
    assert s.iso == 6400 and s.quality == "RAW+JPEG" and s.shutter == "4" and s.focus == :manual
    assert :auto in s.isos and 100 in s.isos
  end

  test "connecting does the handshake: device info, Sony's extra properties, a fresh property blob" do
    {:ok, info, conn} = Sony.connect(conn())
    assert info.model == "ILCE-6000" and info.sony_version == 200
    assert Sony.prop(:iso) in info.sony_props
    # (the a6000 takes "the computer has priority" without listing it among its properties)
    {:ok, props, _} = Sony.props(conn)
    assert props[Sony.prop(:iso)].current == 6400
  end

  test "answers left over from an interrupted conversation don't put every reply one step behind" do
    {:ok, st} = Sim.open([])
    # a reply nobody read: what a program that died mid-transaction leaves in the pipe
    stale = Ptp.container(:data, 0x1001, 7, "stale") <> Ptp.container(:response, 0x2001, 7)
    st = %{st | out: :queue.from_list([stale])}
    {:ok, info, _conn} = Sony.connect(%Ptp.Conn{transport: Sim, state: st})
    assert info.model == "ILCE-6000"
  end

  test "ISO turns to a listed value, even when the dial moves one notch at a time" do
    {:ok, _, conn} = Sony.connect(conn(max_notches: 1))
    assert {:ok, 800, conn} = Sony.set(conn, Sony.prop(:iso), 800)
    {:ok, props, _} = Sony.props(conn)
    assert Sony.describe(props).iso == 800
  end

  test "the shutter, which lists no values, turns by exposure time to the nearest it offers" do
    {:ok, _, conn} = Sony.connect(conn())

    order = fn v ->
      if Sony.shutter_seconds(v) == :bulb, do: -1.0e6, else: -Sony.shutter_seconds(v)
    end

    assert {:ok, v, conn} =
             Sony.set(conn, Sony.prop(:shutter), Sony.shutter_value("1/200"), order: order)

    assert Sony.shutter_words(v) == "1/200"

    assert {:ok, v, _} =
             Sony.set(conn, Sony.prop(:shutter), Sony.shutter_value("1"), order: order)

    assert Sony.shutter_words(v) == "1"
  end

  test "a picture is pressed, waited for, and downloaded: both files for RAW+JPEG" do
    {:ok, _, conn} = Sony.connect(conn())
    assert {:ok, [jpeg, raw], conn} = Sony.capture(conn, exposure_ms: 10)
    assert jpeg.format == :jpeg and binary_part(jpeg.bytes, 0, 2) == <<0xFF, 0xD8>>
    assert raw.format == :arw and raw.name =~ ".ARW"
    # and nothing is left in the camera's memory to come down as the next picture
    {:ok, props, _} = Sony.props(conn)
    assert Sony.describe(props).in_memory == 0
  end

  test "a camera that stops answering is an error, not a hang" do
    {:ok, _, conn} = Sony.connect(conn())
    conn = %{conn | state: %{conn.state | fail_after: conn.state.transfers}}
    assert {:error, :timeout, _} = Sony.props(conn)
  end

  test "shutter speeds in words and back" do
    for w <- ["1/200", "1/60", "1", "4", "30", "2.5", "Bulb"] do
      assert Sony.shutter_words(Sony.shutter_value(w)) == w
    end
  end
end
