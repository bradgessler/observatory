defmodule Firmware.Solix.Session do
  @moduledoc """
  One Anker SOLIX battery, read over Bluetooth: connect, find the SOLIX
  service, turn its notifications on, say hello, answer the station through
  the key exchange (`Firmware.Solix.reply/4`), then pass on every reading
  it sends (every few seconds, by itself). A client of `Bluez.Gatt` and
  nothing else.

  It ends rather than retries, whenever the link does: a connection refused
  or dropped, no SOLIX service, an exchange not finished 30 s after
  connecting, or a minute with no reading. When to try again is
  `Firmware.Batteries`' call. Temporary under its own supervisor, and gone
  as soon as the process it reports to is, so a battery can only ever cost
  its own reading.

  The link is let go in `terminate/2`, whatever the reason: `Bluez.Gatt`
  has three connection slots and does not watch who asked for them, so a
  session that forgot would keep one until BlueZ noticed.

  Each reading goes to `report_to`, stamped with monotonic time:

      {:solix, pid, address, {:reading, %{charge: 100, ..., at: monotonic_ms}}}

  Options: `address` ("F4:9D:8A:B0:25:6A"), `report_to` (a pid), and for
  tests `gatt` (the module, `Bluez.Gatt`) and the waits (`connect_ms`,
  `negotiate_ms`, `hello_again_ms`, `quiet_ms`).
  """
  use GenServer, restart: :temporary
  require Logger

  alias Firmware.Solix

  @compile {:no_warn_undefined, [Bluez.Gatt]}

  # Device1.Connect can take 32 s and resolving services 30 more; Bluez.Gatt
  # says so itself when it gives up, and this is only the backstop
  @connect_ms 75_000
  @negotiate_ms 30_000
  # no answer to hello: say it again (SolixBLE waits 10 s too)
  @hello_again_ms 10_000
  # the station sends every few seconds; a minute of nothing is a dead link
  @quiet_ms 60_000
  # MTU 256 less the 3 bytes of ATT header, as seen on the box
  @fragment_size 253

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts)

  @doc "`\"F4:9D:8A:B0:25:6A\"` as the 48-bit integer `Bluez.Gatt` takes."
  def address_int(address), do: address |> String.replace(":", "") |> String.to_integer(16)

  # -- the process ------------------------------------------------------------------------

  @impl true
  def init(opts) do
    # so terminate/2 runs, and lets the link go, when the supervisor stops us
    Process.flag(:trap_exit, true)
    address = Keyword.fetch!(opts, :address)
    report_to = Keyword.fetch!(opts, :report_to)
    send(self(), :connect)

    {:ok,
     %{
       address: address,
       addr: address_int(address),
       report_to: report_to,
       report_ref: Process.monitor(report_to),
       gatt: Keyword.get(opts, :gatt, Bluez.Gatt),
       waits: %{
         connect: Keyword.get(opts, :connect_ms, @connect_ms),
         negotiate: Keyword.get(opts, :negotiate_ms, @negotiate_ms),
         hello_again: Keyword.get(opts, :hello_again_ms, @hello_again_ms),
         quiet: Keyword.get(opts, :quiet_ms, @quiet_ms)
       },
       stage: :connecting,
       chars: [],
       command: nil,
       telemetry: nil,
       fragment_sizes: [@fragment_size],
       frags: %{},
       secret: nil,
       answered: false,
       deadline: nil,
       timer: nil
     }}
  end

  @impl true
  def handle_info(:connect, s) do
    gatt(s, :connect, [s.addr, [], self()])
    {:noreply, arm(s, :connect)}
  end

  # connected: find the service; the whole exchange has 30 s from here
  def handle_info({:gatt_connection, addr, {:ok, mtu}}, %{addr: addr, stage: :connecting} = s) do
    gatt(s, :get_services, [addr])
    sizes = if is_integer(mtu) and mtu > 64, do: [mtu - 3], else: s.fragment_sizes
    {:noreply, arm(%{s | stage: :discovering, fragment_sizes: sizes}, :negotiate)}
  end

  # refused, or dropped: nothing to retry here
  def handle_info({:gatt_connection, addr, {:error, code}}, %{addr: addr} = s) do
    why = if s.stage == :connecting, do: {:connect_failed, code}, else: :disconnected
    {:stop, {:shutdown, why}, s}
  end

  def handle_info({:gatt_service, addr, service}, %{addr: addr, stage: :discovering} = s),
    do: {:noreply, %{s | chars: service.characteristics ++ s.chars}}

  def handle_info({:gatt_services_done, addr}, %{addr: addr, stage: :discovering} = s) do
    command = handle_of(s.chars, Solix.command_uuid())
    telemetry = handle_of(s.chars, Solix.telemetry_uuid())

    if command && telemetry do
      gatt(s, :notify, [addr, telemetry, true])
      {:noreply, %{s | stage: :subscribing, command: command, telemetry: telemetry, chars: []}}
    else
      {:stop, {:shutdown, :no_solix_service}, s}
    end
  end

  # get_services on a link that is not ready answers as a failed read of handle 0
  def handle_info({:gatt_read, addr, 0, {:error, _}}, %{addr: addr, stage: :discovering} = s),
    do: {:stop, {:shutdown, :no_services}, s}

  def handle_info({:gatt_notify, addr, handle, {:ok, _}}, %{addr: addr, telemetry: handle, stage: :subscribing} = s) do
    hello(s)
    {:noreply, %{s | stage: :negotiating}}
  end

  def handle_info({:gatt_notify, addr, handle, {:error, code}}, %{addr: addr, telemetry: handle} = s),
    do: {:stop, {:shutdown, {:notify_failed, code}}, s}

  def handle_info(:hello_again, %{stage: :negotiating, answered: false} = s) do
    Logger.debug("Solix #{s.address}: no answer to hello; again")
    hello(s)
    {:noreply, s}
  end

  def handle_info(:hello_again, s), do: {:noreply, s}

  def handle_info({:gatt_notify_data, addr, _handle, data}, %{addr: addr} = s) when is_binary(data),
    do: {:noreply, data(s, data)}

  # the station hears the next packet anyway, and a stuck exchange runs out of time
  def handle_info({:gatt_write, addr, handle, {:error, code}}, %{addr: addr} = s) do
    Logger.debug("Solix #{s.address}: write to #{handle} failed (#{inspect(code)})")
    {:noreply, s}
  end

  def handle_info({:deadline, ref, why}, %{deadline: ref} = s), do: {:stop, {:shutdown, why}, s}

  # whoever wanted the readings is gone
  def handle_info({:DOWN, ref, :process, _, _}, %{report_ref: ref} = s), do: {:stop, {:shutdown, :unwanted}, s}

  def handle_info(_, s), do: {:noreply, s}

  @impl true
  def terminate(_why, s), do: gatt(s, :disconnect, [s.addr])

  # -- the conversation --------------------------------------------------------------------

  defp hello(s) do
    write(s, Solix.hello(System.os_time(:second)))
    Process.send_after(self(), :hello_again, s.waits.hello_again)
  end

  # a notification: a packet, or one fragment of one (a packet the full size
  # of the link or of the station's own limit, or more of a payload begun)
  defp data(s, data) do
    case Solix.parse_packet(data) do
      {:ok, pk} ->
        key = pk.pattern <> pk.cmd

        if byte_size(data) in s.fragment_sizes or Map.has_key?(s.frags, key) do
          case Solix.reassemble(s.frags, key, pk.payload) do
            {:done, payload, frags} -> packet(%{s | frags: frags}, %{pk | payload: payload})
            {:more, frags} -> %{s | frags: frags}
          end
        else
          packet(s, pk)
        end

      {:error, why} ->
        Logger.debug("Solix #{s.address}: unreadable notification (#{why}): #{Base.encode16(data)}")
        s
    end
  end

  defp packet(s, pk) do
    cond do
      Solix.negotiation?(pk) -> negotiate(%{s | answered: true}, pk)
      Solix.session?(pk) -> reading(s, pk)
      true -> s
    end
  end

  defp negotiate(s, pk) do
    params = Solix.parse_params(plain(pk.payload, s.secret))
    # the station says how long its packets run before it splits them (as
    # SolixBLE reads it; unconfirmed on the C200, so the link's size stays too)
    s = if pk.cmd == <<0x08, 0x03>>, do: %{s | fragment_sizes: Enum.uniq(s.fragment_sizes ++ station_size(params[0xA2]))}, else: s

    case Solix.reply(pk.cmd, params, System.os_time(:second)) do
      {:send, packet} ->
        write(s, packet)
        s

      {:send, packet, secret} ->
        write(s, packet)
        %{s | secret: secret}

      :done ->
        live(s)

      :unknown ->
        s
    end
  end

  # the first reading is as good as the exchange's last word: some stations
  # never send that
  defp reading(s, pk) do
    case Solix.read_telemetry(pk.payload, s.secret) do
      nil ->
        s

      reading ->
        s = live(s)
        report(s, {:reading, Map.put(reading, :at, System.monotonic_time(:millisecond))})
        arm(s, :quiet)
    end
  end

  defp live(%{stage: :live} = s), do: s

  defp live(s) do
    Logger.debug("Solix #{s.address}: live")
    arm(%{s | stage: :live}, :quiet)
  end

  defp plain(payload, nil), do: payload

  defp plain(payload, secret) do
    case Solix.decrypt(payload, secret) do
      {:ok, plain} -> plain
      _ -> payload
    end
  end

  defp station_size(bytes) when is_binary(bytes) and bytes != "" do
    case :binary.decode_unsigned(bytes, :little) do
      n when n in 20..512 -> [n]
      _ -> []
    end
  end

  defp station_size(_), do: []

  defp handle_of(chars, uuid), do: Enum.find_value(chars, fn c -> if c.uuid == uuid, do: c.handle end)

  # -- plumbing ------------------------------------------------------------------------------

  # one deadline at a time: a new stage's replaces the last one's
  defp arm(s, what) do
    if s.timer, do: Process.cancel_timer(s.timer)
    ref = make_ref()
    why = %{connect: :connect_timeout, negotiate: :negotiation_timeout, quiet: :quiet}[what]
    %{s | deadline: ref, timer: Process.send_after(self(), {:deadline, ref, why}, s.waits[what])}
  end

  defp write(s, packet), do: gatt(s, :write, [s.addr, s.command, packet, true])

  defp report(s, event), do: send(s.report_to, {:solix, self(), s.address, event})

  # Bluez.Gatt takes casts, so this never waits; and with the stack down (or
  # not in this system) it is a no-op, not a crash
  defp gatt(s, fun, args) do
    apply(s.gatt, fun, args)
  rescue
    _ -> :error
  catch
    _, _ -> :error
  end
end
