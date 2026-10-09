defmodule Firmware.BatteriesTest do
  # the fakes below answer to one registered name
  use ExUnit.Case, async: false

  alias Firmware.Batteries

  @low "F4:9D:8A:9D:6A:E0"
  @high "F4:9D:8A:B0:25:6A"
  @third "F4:9D:8A:FF:00:01"

  # monotonic time is negative on the BEAM; every time here is relative to it
  defp now, do: System.monotonic_time(:millisecond)

  defp entry(address, fields), do: Map.merge(Batteries.entry(address), Map.new(fields))

  defp reading(charge, at, fields \\ []),
    do: Map.merge(%{charge: charge, watts_out: 0, watts_in: 0, temp_c: 25, time_left_h: 231.0, at: at}, Map.new(fields))

  describe "the rules" do
    test "only Anker SOLIX adverts are batteries" do
      assert Batteries.solix?(%{name: "Anker SOLIX C200 DC"})
      refute Batteries.solix?(%{name: "Xbox Wireless Controller"})
      refute Batteries.solix?(%{name: nil})
    end

    test "a session that keeps failing waits 10 s, 30 s, then 2 min" do
      assert Enum.map(0..5, &Batteries.backoff/1) == [10_000, 10_000, 30_000, 120_000, 120_000, 120_000]
    end

    test "live for a minute after a reading, then stale while still around, lost once not" do
      t = now()
      assert Batteries.state(entry(@low, reading: reading(100, t - 10_000), heard_at: t), t) == :live
      assert Batteries.state(entry(@low, reading: reading(100, t - 61_000), session: self()), t) == :stale
      assert Batteries.state(entry(@low, reading: reading(100, t - 61_000), heard_at: t - 5_000), t) == :stale
      assert Batteries.state(entry(@low, reading: reading(100, t - 300_000), heard_at: t - 130_000), t) == :lost
      assert Batteries.state(entry(@low, session: self()), t) == :connecting
      assert Batteries.state(entry(@low, heard_at: t - 1_000), t) == :connecting
      assert Batteries.state(entry(@low, heard_at: t - 130_000), t) == :lost
    end

    test "numbered by address, so Battery 1 stays Battery 1" do
      t = now()
      entries = [entry(@high, heard_at: t), entry(@low, heard_at: t, reading: reading(16, t))]

      assert [%{n: 1, address: @low, state: :live, reading: %{charge: 16}}, %{n: 2, address: @high, state: :connecting, reading: nil}] =
               Batteries.number(entries, t)

      assert Batteries.number(Enum.reverse(entries), t) == Batteries.number(entries, t)
    end

    test "starts heard and due batteries, lowest address first, two at a time" do
      t = now()
      heard = fn a -> entry(a, heard_at: t) end
      assert Enum.map(Batteries.to_start([heard.(@third), heard.(@high), heard.(@low)], t), & &1.address) == [@low, @high]

      running = entry(@low, heard_at: t, session: self())
      assert Enum.map(Batteries.to_start([running, heard.(@high), heard.(@third)], t), & &1.address) == [@high]

      waiting = entry(@high, heard_at: t, retry_at: t + 5_000)
      gone = entry(@third, heard_at: t - 130_000)
      assert Batteries.to_start([waiting, gone], t) == []
      assert [%{address: @high}] = Batteries.to_start([%{waiting | retry_at: t - 1}], t)

      both = [entry(@low, session: self()), entry(@high, session: self()), heard.(@third)]
      assert Batteries.to_start(both, t) == []
    end

    test "one word per battery for the flight log" do
      t = now()

      list = [
        %{n: 1, state: :live, reading: reading(100, t)},
        %{n: 2, state: :live, reading: reading(80, t, watts_out: 13, watts_in: 60, temp_c: 26)},
        %{n: 3, state: :stale, reading: reading(16, t, watts_out: 13, temp_c: 26)},
        %{n: 4, state: :connecting, reading: nil},
        %{n: 5, state: :lost, reading: reading(50, t)}
      ]

      assert Batteries.brief(list) == "1:100%/0W/25C 2:80%/13W/in60W/26C 3:stale/16%/13W/26C 4:connecting 5:lost"
      assert Batteries.brief([%{n: 1, state: :live, reading: %{charge: nil, watts_out: nil, watts_in: nil, temp_c: nil}}]) == "1:?%/?W/?C"
    end
  end

  # -- the process ------------------------------------------------------------------------

  defmodule FakeSession do
    use GenServer, restart: :temporary
    def start_link(opts), do: GenServer.start_link(__MODULE__, opts)

    @impl true
    def init(opts) do
      send(:batteries_test, {:session, self(), opts[:address], opts[:report_to]})
      {:ok, opts}
    end
  end

  defmodule FakeGatt do
    def disconnect(addr), do: send(:batteries_test, {:gatt, :disconnect, [addr]})
  end

  describe "the process" do
    setup do
      Process.register(self(), :batteries_test)
      test = self()
      {:ok, heard} = Agent.start_link(fn -> [] end)
      sup = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

      pid =
        start_supervised!(
          {Batteries,
           name: :batteries_under_test,
           scan_ms: 3_600_000,
           nearby: fn -> Agent.get(heard, & &1) end,
           up?: fn -> true end,
           sup: sup,
           session: FakeSession,
           gatt: FakeGatt,
           broadcast: &send(test, {:broadcast, &1})}
        )

      hear = fn devices -> Agent.update(heard, fn _ -> Enum.map(devices, &Map.put_new(&1, :at, now())) end) end
      %{pid: pid, hear: hear}
    end

    test "connects to every battery heard, two at a time, and numbers them", %{pid: pid, hear: hear} do
      hear.([
        %{address: @high, name: "Anker SOLIX C200 DC"},
        %{address: "AA:BB:CC:DD:EE:FF", name: "Xbox Wireless Controller"},
        %{address: @third, name: "Anker SOLIX C200 DC"},
        %{address: @low, name: "Anker SOLIX C200 DC"}
      ])

      send(pid, :scan)
      assert_receive {:session, low, @low, ^pid}
      assert_receive {:session, high, @high, ^pid}
      refute_receive {:session, _, @third, _}, 50

      assert [%{n: 1, address: @low, state: :connecting}, %{n: 2, address: @high}, %{n: 3, address: @third}] =
               Batteries.list(:batteries_under_test)

      # a reading makes it live, and goes out to the pages
      send(pid, {:solix, high, @high, {:reading, reading(100, now())}})
      assert_receive {:broadcast, [_, %{n: 2, state: :live, reading: %{charge: 100}}, _]}

      # a reading from a session that is not this battery's is not believed
      send(pid, {:solix, self(), @low, {:reading, reading(1, now())}})
      assert [%{n: 1, reading: nil} | _] = Batteries.list(:batteries_under_test)

      # a session that dies frees its link and its turn: the third gets it,
      # and the first waits its 10 s
      Process.exit(low, :kill)
      assert_receive {:gatt, :disconnect, [0xF49D8A9D6AE0]}
      send(pid, :scan)
      assert_receive {:session, _, @third, ^pid}
      refute_receive {:session, _, @low, _}, 50
      assert Process.alive?(pid)
    end

    test "nothing starts while Bluetooth is down, and a battery long gone is forgotten", %{hear: hear} do
      pid =
        start_supervised!(
          {Batteries,
           name: :batteries_down,
           scan_ms: 3_600_000,
           nearby: fn -> [%{address: @low, name: "Anker SOLIX C200 DC", at: now()}] end,
           up?: fn -> false end,
           sup: :nowhere,
           session: FakeSession,
           gatt: FakeGatt,
           broadcast: fn _ -> :ok end},
          id: :down
        )

      send(pid, :scan)
      refute_receive {:session, _, _, _}, 50
      assert [%{n: 1, state: :connecting}] = Batteries.list(:batteries_down)

      hear.([%{address: @low, name: "Anker SOLIX C200 DC", at: now() - 16 * 60_000}])
      send(:batteries_under_test, :scan)
      refute_receive {:session, _, _, _}, 50
      assert Batteries.list(:batteries_under_test) == []
    end

    @tag :capture_log
    test "a session that cannot start is tried again later, not crashed on" do
      pid =
        start_supervised!(
          {Batteries,
           name: :batteries_no_sup,
           scan_ms: 3_600_000,
           nearby: fn -> [%{address: @low, name: "Anker SOLIX C200 DC", at: now()}] end,
           up?: fn -> true end,
           sup: :no_such_supervisor,
           session: FakeSession,
           gatt: FakeGatt,
           broadcast: fn _ -> :ok end},
          id: :no_sup
        )

      send(pid, :scan)
      assert [%{n: 1, state: :connecting}] = Batteries.list(:batteries_no_sup)
      assert Process.alive?(pid)
    end

    test "list is empty, not an exit, when nothing is running" do
      assert Batteries.list(:no_such_batteries) == []
    end
  end
end
