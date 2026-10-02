defmodule Firmware.SolixTest do
  use ExUnit.Case, async: true

  alias Firmware.Solix

  # SolixBLE's recorded handshake (its const.py), all sent at the same second
  @at 0x698CAD42
  @hello "ff0936000300010001a10442ad8c69a22462326463306231372d623735642d346162662d626136652d656337633939376332336537b9"
  @reply_0801 "ff093d000300010003a10442ad8c69a22462326463306231372d623735642d346162662d626136652d656337633939376332336537a30120a40200f064"
  @reply_0803 "ff0936000300010029a10442ad8c69a22462326463306231372d623735642d346162662d626136652d65633763393937633233653791"
  @reply_0829 "ff0940000300010005a10442ad8c69a22462326463306231372d623735642d346162662d626136652d656337633939376332336537a30120a40200f0a50140fb"
  @reply_0805 "ff094c000300010021a140060ea168f232aedb37fb2d120c49180329ac72ab5ec3eb8fd30a2f252dc5e151dabccd9b1dc1e288704ca760a0d8c918e5c94823a1f609a4bf07fb4c33ee219085"

  defp hex(s), do: Base.decode16!(s, case: :lower)

  test "the hello and each plain reply are byte for byte what SolixBLE sends" do
    assert Solix.hello(@at) == hex(@hello)
    assert {:send, p1} = Solix.reply(<<0x08, 0x01>>, %{}, @at)
    assert {:send, p2} = Solix.reply(<<0x08, 0x03>>, %{}, @at)
    assert {:send, p3} = Solix.reply(<<0x08, 0x29>>, %{}, @at)
    assert {:send, p4} = Solix.reply(<<0x08, 0x05>>, %{}, @at)
    assert p1 == hex(@reply_0801)
    assert p2 == hex(@reply_0803)
    assert p3 == hex(@reply_0829)
    # which also proves our public key is the one their private key makes
    assert p4 == hex(@reply_0805)
  end

  test "packets parse back, and a bad checksum or length is refused" do
    assert {:ok, %{pattern: <<3, 0, 1>>, cmd: <<0, 1>>, payload: payload}} = Solix.parse_packet(hex(@hello))
    assert %{0xA1 => <<0x42, 0xAD, 0x8C, 0x69>>, 0xA2 => "b2dc0b17-b75d-4abf-ba6e-ec7c997c23e7"} = Solix.parse_params(payload)

    packet = hex(@hello)
    n = byte_size(packet) - 1
    <<body::binary-size(^n), sum>> = packet
    assert Solix.parse_packet(body <> <<Bitwise.bxor(sum, 1)>>) == {:error, :checksum}
    assert Solix.parse_packet(body) == {:error, :length}
    assert Solix.parse_packet(<<1, 2, 3>>) == {:error, :not_a_packet}
  end

  test "parameters keep their type tag, skip a leading 00, and stop at a short field" do
    payload = <<0x00, 0xA1, 1, 0x21, 0xB7, 2, 0x01, 17, 0xB8, 3, 0x02, 0x10, 0x27, 0xC3, 9, 0x00>>
    params = Solix.parse_params(payload)
    assert params[0xA1] == <<0x21>>
    assert params[0xB7] == <<0x01, 17>>
    assert Solix.uint(params, 0xB7) == 17
    assert Solix.uint(params, 0xB8) == 10_000
    refute Map.has_key?(params, 0xC3)
    assert Solix.uint(params, 0xFF) == nil
  end

  test "the exchange gives both sides the same secret, and the cipher round-trips" do
    {<<4, station_xy::binary-64>>, station_priv} = :crypto.generate_key(:ecdh, :secp256r1)
    ours = Solix.shared_secret(station_xy)
    theirs = :crypto.compute_key(:ecdh, <<4, Solix.public_key()::binary>>, station_priv, :secp256r1)
    assert ours == theirs and byte_size(ours) == 32

    telemetry = Solix.params([{0xA1, <<0x21>>}, {0xB7, <<0x01, 100>>}])
    sealed = Solix.encrypt(telemetry, ours)
    assert rem(byte_size(sealed), 16) == 0
    assert Solix.decrypt(sealed, ours) == {:ok, telemetry}
    assert Solix.decrypt(<<1, 2, 3>>, ours) == {:error, :decrypt}
  end

  test "the station's key answer gives the secret and an encrypted last word" do
    {<<4, station_xy::binary-64>>, _} = :crypto.generate_key(:ecdh, :secp256r1)
    assert {:send, packet, secret} = Solix.reply(<<0x08, 0x21>>, %{0xA1 => station_xy}, @at, "PST8PDT")
    assert {:ok, %{pattern: <<3, 0, 1>>, cmd: <<0x40, 0x22>>, payload: sealed}} = Solix.parse_packet(packet)
    assert {:ok, plain} = Solix.decrypt(sealed, secret)
    assert Solix.parse_params(plain)[0xA5] == "PST8PDT"
    assert Solix.reply(<<0x48, 0x22>>, %{}, @at) == :done
    assert Solix.reply(<<0x77, 0x77>>, %{}, @at) == :unknown
  end

  test "fragments carry their index and total in the first byte" do
    assert Solix.fragment(<<0x13, "abc">>) == {1, 3, "abc"}
  end

  test "fragments come back together in order; one out of order drops the lot" do
    key = <<3, 1, 0x0F, 4, 2>>
    assert {:more, b} = Solix.reassemble(%{}, key, <<0x13, "ab">>)
    assert {:more, b} = Solix.reassemble(b, key, <<0x23, "cd">>)
    assert {:done, "abcdef", b} = Solix.reassemble(b, key, <<0x33, "ef">>)
    assert b == %{}

    assert {:more, b} = Solix.reassemble(%{}, key, <<0x12, "ab">>)
    assert Solix.reassemble(b, key, <<0x33, "ef">>) == {:more, %{}}
    # a first fragment starts over, whatever came before
    assert {:more, b} = Solix.reassemble(%{key => ["old"]}, key, <<0x12, "ab">>)
    assert {:done, "abcd", _} = Solix.reassemble(b, key, <<0x22, "cd">>)
    assert Solix.reassemble(%{}, key, <<>>) == {:more, %{}}
  end

  # Fields from the C200 DCs on the box: one full and idle, one at 16%
  # with a load on it (the other 30-odd fields are left out)
  @full %{
    0xA1 => <<0x31>>,
    0xA3 => <<2, 0x06, 0x09>>,
    0xAD => <<2, 0, 0>>,
    0xB5 => <<1, 0x19>>,
    0xB7 => <<1, 0x64>>,
    0xB8 => <<1, 0x64>>,
    0xAF => <<2, 0x24, 0x36>>,
    0xB0 => <<2, 0x6F, 0>>,
    0xC3 => <<0, "AZVD630F08500369">>
  }

  test "telemetry reads as a battery: charge, draw, time left, temperature" do
    assert %{
             charge: 100,
             health: 100,
             temp_c: 25,
             watts_out: 0,
             time_left_h: 231.0,
             capacity_mah: 13_860,
             firmware: "1.1.1",
             serial: "AZVD630F08500369",
             watts_in: nil
           } = Solix.telemetry(@full)

    low = Map.merge(@full, %{0xB7 => <<1, 0x10>>, 0xAD => <<2, 0x0D, 0>>, 0xA3 => <<2, 0x16, 0>>, 0xB5 => <<1, 0x1A>>})
    assert %{charge: 16, watts_out: 13, time_left_h: 2.2, temp_c: 26} = Solix.telemetry(low)

    # below freezing is a signed byte
    assert Solix.telemetry(%{0xB5 => <<1, 0xFB>>}).temp_c == -5
    assert %{charge: nil, serial: nil, firmware: nil, time_left_h: nil} = Solix.telemetry(%{})
  end

  test "a payload reads plain, or decrypted when plain is not telemetry, or not at all" do
    payload = <<0x00>> <> Solix.params(Enum.sort(@full))
    assert %{charge: 100, serial: "AZVD630F08500369"} = Solix.read_telemetry(payload)

    # a fixed key, so what the ciphertext happens to look like plain is the same every run
    secret = :binary.copy(<<7>>, 32)
    assert Solix.read_telemetry(payload, secret).charge == 100
    assert Solix.read_telemetry(Solix.encrypt(payload, secret), secret).charge == 100
    assert Solix.read_telemetry(Solix.encrypt(payload, secret)) == nil
    assert Solix.read_telemetry(Solix.params([{0xA1, <<0x21>>}])) == nil
    assert Solix.read_telemetry(Solix.params([{0xB7, <<1, 200>>}])) == nil
  end
end
