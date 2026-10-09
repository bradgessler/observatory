defmodule Firmware.Solix.SessionTest do
  # the fake Bluez.Gatt below answers to one registered name
  use ExUnit.Case, async: false

  alias Firmware.Solix
  alias Firmware.Solix.Session

  # Bluez.Gatt as a session sees it: every call is a cast, told to the test
  defmodule FakeGatt do
    def connect(addr, opts, subscriber), do: tell(:connect, [addr, opts, subscriber])
    def get_services(addr), do: tell(:get_services, [addr])
    def notify(addr, handle, on?), do: tell(:notify, [addr, handle, on?])
    def write(addr, handle, data, response?), do: tell(:write, [addr, handle, data, response?])
    def disconnect(addr), do: tell(:disconnect, [addr])
    defp tell(fun, args), do: send(:fake_gatt, {:gatt, fun, args})
  end

  @address "F4:9D:8A:B0:25:6A"
  @addr 0xF49D8AB0256A
  @negotiation <<3, 0, 1>>
  @telemetry <<3, 1, 0x0F>>
  # handles as the C200 DC gave them; the session looks them up by UUID
  @command 12
  @notify 14

  setup do
    Process.register(self(), :fake_gatt)
    :ok
  end

  # unlinked: a session ending is what half of these are about
  defp start(opts \\ []) do
    {:ok, pid} = GenServer.start(Session, [address: @address, report_to: self(), gatt: FakeGatt] ++ opts)
    pid
  end

  # the station's side: its answer to what the session just wrote
  defp station(pid, cmd, params) do
    send(pid, {:gatt_notify_data, @addr, @notify, Solix.packet(@negotiation, cmd, Solix.params(params))})
  end

  defp written do
    assert_receive {:gatt, :write, [@addr, @command, packet, true]}
    {:ok, pk} = Solix.parse_packet(packet)
    pk
  end

  defp connect_and_subscribe(pid) do
    assert_receive {:gatt, :connect, [@addr, [], ^pid]}
    send(pid, {:gatt_connection, @addr, {:ok, 256}})
    assert_receive {:gatt, :get_services, [@addr]}

    send(pid, {:gatt_service, @addr, %{uuid: <<0x1801::128>>, handle: 1, characteristics: [%{uuid: <<0x2A05::128>>, handle: 3}]}})

    send(
      pid,
      {:gatt_service, @addr,
       %{
         uuid: Solix.service_uuid(),
         handle: 10,
         characteristics: [%{uuid: Solix.command_uuid(), handle: @command}, %{uuid: Solix.telemetry_uuid(), handle: @notify}]
       }}
    )

    send(pid, {:gatt_services_done, @addr})
    assert_receive {:gatt, :notify, [@addr, @notify, true]}
    send(pid, {:gatt_notify, @addr, @notify, {:ok, :done}})
    assert %{cmd: <<0, 1>>} = written()
  end

  # the five exchanges the C200 DC went through, then its public key
  defp negotiate(pid) do
    station(pid, <<8, 1>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 3>>} = written()
    station(pid, <<8, 3>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 0x29>>} = written()
    station(pid, <<8, 0x29>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 5>>} = written()
    station(pid, <<8, 5>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 0x21>>, payload: ours} = written()

    {<<4, station_xy::binary-64>>, station_priv} = :crypto.generate_key(:ecdh, :secp256r1)
    station(pid, <<8, 0x21>>, [{0xA1, station_xy}])
    assert %{cmd: <<0x40, 0x22>>} = written()
    %{0xA1 => our_xy} = Solix.parse_params(ours)
    :crypto.compute_key(:ecdh, <<4, our_xy::binary>>, station_priv, :secp256r1)
  end

  # the C200 DC's telemetry: cmd 0402, plain
  defp telemetry(charge, extra \\ []) do
    payload = <<0>> <> Solix.params([{0xA1, <<0x31>>}, {0xAD, <<2, 13, 0>>}, {0xB5, <<1, 25>>}, {0xB7, <<1, charge>>}] ++ extra)
    {payload, Solix.packet(@telemetry, <<4, 2>>, payload)}
  end

  test "connects, finds the SOLIX handles, goes through the exchange, and passes on each reading" do
    pid = start()
    connect_and_subscribe(pid)
    secret = negotiate(pid)
    assert byte_size(secret) == 32

    {_, packet} = telemetry(100)
    send(pid, {:gatt_notify_data, @addr, @notify, packet})
    assert_receive {:solix, ^pid, @address, {:reading, %{charge: 100, watts_out: 13, temp_c: 25, at: at}}}
    assert is_integer(at)

    {_, packet} = telemetry(99)
    send(pid, {:gatt_notify_data, @addr, @notify, packet})
    assert_receive {:solix, ^pid, @address, {:reading, %{charge: 99}}}
  end

  test "a payload longer than the link arrives in fragments and reads as one" do
    pid = start()
    connect_and_subscribe(pid)
    negotiate(pid)

    # a field of filler makes it longer than one 253-byte packet carries
    {payload, _} = telemetry(16, [{0xD0, :binary.copy(<<0xEE>>, 250)}])
    <<first::binary-242, rest::binary>> = payload
    one = Solix.packet(@telemetry, <<4, 2>>, <<0x12, first::binary>>)
    two = Solix.packet(@telemetry, <<4, 2>>, <<0x22, rest::binary>>)
    assert byte_size(one) == 253

    send(pid, {:gatt_notify_data, @addr, @notify, one})
    refute_receive {:solix, ^pid, _, {:reading, _}}, 50
    send(pid, {:gatt_notify_data, @addr, @notify, two})
    assert_receive {:solix, ^pid, @address, {:reading, %{charge: 16}}}
  end

  test "the station's own packet limit, from its 0803, splits payloads too" do
    pid = start()
    connect_and_subscribe(pid)
    station(pid, <<8, 1>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 3>>} = written()
    station(pid, <<8, 3>>, [{0xA1, <<0x21>>}, {0xA2, <<200>>}])
    assert %{cmd: <<0, 0x29>>} = written()

    {payload, _} = telemetry(55, [{0xD0, :binary.copy(<<0xEE>>, 250)}])
    <<first::binary-189, rest::binary>> = payload
    one = Solix.packet(@telemetry, <<4, 2>>, <<0x12, first::binary>>)
    assert byte_size(one) == 200
    send(pid, {:gatt_notify_data, @addr, @notify, one})
    send(pid, {:gatt_notify_data, @addr, @notify, Solix.packet(@telemetry, <<4, 2>>, <<0x22, rest::binary>>)})
    assert_receive {:solix, ^pid, @address, {:reading, %{charge: 55}}}
  end

  test "a reading is a reading without the exchange's last word, and garbage is not one" do
    pid = start()
    connect_and_subscribe(pid)
    send(pid, {:gatt_notify_data, @addr, @notify, <<1, 2, 3>>})
    send(pid, {:gatt_notify_data, @addr, @notify, Solix.packet(@telemetry, <<4, 2>>, "not telemetry")})
    {_, packet} = telemetry(42)
    send(pid, {:gatt_notify_data, @addr, @notify, packet})
    assert_receive {:solix, ^pid, @address, {:reading, %{charge: 42}}}
    assert Process.alive?(pid)
  end

  test "says hello again when the station does not answer" do
    pid = start(hello_again_ms: 30)
    connect_and_subscribe(pid)
    assert %{cmd: <<0, 1>>} = written()
    station(pid, <<8, 1>>, [{0xA1, <<0x21>>}])
    assert %{cmd: <<0, 3>>} = written()
    refute_receive {:gatt, :write, _}, 80
  end

  test "a dropped link ends the session and lets the link go" do
    pid = start()
    ref = Process.monitor(pid)
    connect_and_subscribe(pid)
    send(pid, {:gatt_connection, @addr, {:error, -1}})
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :disconnected}}
    assert_receive {:gatt, :disconnect, [@addr]}
  end

  test "a refused connection, a missing service, a stuck exchange and a quiet station each end it" do
    pid = start()
    ref = Process.monitor(pid)
    send(pid, {:gatt_connection, @addr, {:error, -1}})
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, {:connect_failed, -1}}}

    pid = start()
    ref = Process.monitor(pid)
    send(pid, {:gatt_connection, @addr, {:ok, 256}})
    send(pid, {:gatt_services_done, @addr})
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :no_solix_service}}

    pid = start(negotiate_ms: 50)
    ref = Process.monitor(pid)
    connect_and_subscribe(pid)
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :negotiation_timeout}}

    pid = start(connect_ms: 50)
    ref = Process.monitor(pid)
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :connect_timeout}}

    pid = start(quiet_ms: 50)
    ref = Process.monitor(pid)
    connect_and_subscribe(pid)
    {_, packet} = telemetry(80)
    send(pid, {:gatt_notify_data, @addr, @notify, packet})
    assert_receive {:solix, ^pid, _, {:reading, %{charge: 80}}}
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :quiet}}
  end

  test "ends when whoever it reports to is gone" do
    test = self()

    parent =
      spawn(fn ->
        {:ok, pid} = GenServer.start(Session, address: @address, report_to: self(), gatt: FakeGatt)
        send(test, {:session, pid})

        receive do
          :stop -> :ok
        end
      end)

    assert_receive {:session, pid}
    ref = Process.monitor(pid)
    send(parent, :stop)
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :unwanted}}
    assert_receive {:gatt, :disconnect, [@addr]}
  end

  test "the address as the integer Bluez.Gatt takes" do
    assert Session.address_int("F4:9D:8A:B0:25:6A") == 0xF49D8AB0256A
  end
end
