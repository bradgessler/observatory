defmodule Firmware.Solix do
  @moduledoc """
  The Bluetooth protocol of Anker SOLIX power stations (the C200 DC on the
  box's batteries), pure: framing, parameters, the key exchange and the
  cipher. `Firmware.Solix.Session` drives it over a connection.

  Ported from SolixBLE (Harvey Lelliott, MIT,
  https://github.com/flip-dots/SolixBLE), which worked it out.

  ## Packets

      ff 09 | length u16 LE | pattern 3B | cmd 2B | payload | xor of all before

  `length` counts the whole packet. Patterns: `030001` negotiation,
  `03010f`/`030111` telemetry, `03000f` commands. A payload longer than the
  link carries is split into fragments, each starting with one byte:
  index (high nibble, from 1) and total (low nibble).

  ## Parameters

  A payload is a list of `key, length, bytes` (keys `a1`, `a2`, ...),
  sometimes after one `00`. Where the length is over 1, the first byte is a
  type tag; values here keep it, and readers skip it (SolixBLE's
  `value_legacy`).

  ## Session

  Six plain exchanges, then everything is encrypted: an ECDH on P-256 (a
  fixed private key on our side; there is nothing to protect but a battery
  reading ten metres away) gives 32 bytes, the first 16 the AES-128-CBC key
  and the last 16 the IV, used for every message, PKCS#7 padded. After that
  the station sends telemetry by itself, pattern `03010f`, cmd `c402`,
  `4300` or `c405`.

  The C200 DC, on the box: telemetry every few seconds as cmd `0402`, and
  plain, even after the exchange. So `read_telemetry/2` reads a payload
  plain first and decrypts only one that does not read as telemetry.
  """

  import Bitwise

  @negotiation <<0x03, 0x00, 0x01>>
  @telemetry_patterns [<<0x03, 0x01, 0x0F>>, <<0x03, 0x01, 0x11>>]
  @telemetry_cmds [<<0xC4, 0x02>>, <<0x43, 0x00>>, <<0xC4, 0x05>>]

  # SolixBLE's constants: the identity we introduce ourselves with, and the
  # key pair for the exchange
  @client_uuid "b2dc0b17-b75d-4abf-ba6e-ec7c997c23e7"
  @private_key Base.decode16!("7DFBEA61CD95CEE49C458AD7419E817F1ADE9A66136DE3C7D5787AF1458E39F4")

  @doc "The GATT service and its two characteristics (UUID bytes as BlueZ gives them)."
  def service_uuid, do: uuid("8c850001-0302-41c5-b46e-cf057c562025")
  def command_uuid, do: uuid("8c850002-0302-41c5-b46e-cf057c562025")
  def telemetry_uuid, do: uuid("8c850003-0302-41c5-b46e-cf057c562025")

  defp uuid(s), do: s |> String.replace("-", "") |> Base.decode16!(case: :lower)

  # -- packets -------------------------------------------------------------------------

  @doc "A packet: pattern and cmd as binaries, payload already encrypted if it is to be."
  def packet(pattern, cmd, payload) do
    body = <<0xFF, 0x09, byte_size(payload) + 10::little-16, pattern::binary-3, cmd::binary-2, payload::binary>>
    body <> <<xor(body)>>
  end

  @doc "`{:ok, %{pattern:, cmd:, payload:}}` or `{:error, why}`."
  def parse_packet(<<0xFF, 0x09, len::little-16, _::binary>> = data) when byte_size(data) == len do
    n = len - 10
    b = len - 1
    <<body::binary-size(^b), sum>> = data
    <<_::binary-4, pattern::binary-3, cmd::binary-2, payload::binary-size(^n)>> = body

    if xor(body) == sum,
      do: {:ok, %{pattern: pattern, cmd: cmd, payload: payload}},
      else: {:error, :checksum}
  end

  def parse_packet(<<0xFF, 0x09, _::binary>>), do: {:error, :length}
  def parse_packet(_), do: {:error, :not_a_packet}

  defp xor(bin), do: for(<<b <- bin>>, reduce: 0, do: (acc -> bxor(acc, b)))

  @doc "A fragment's index, total and data."
  def fragment(<<index::4, total::4, data::binary>>), do: {index, total, data}

  @doc """
  One more fragment of the payload `key` (pattern and cmd):
  `{:done, payload, buffers}` once the last is in, else `{:more, buffers}`.
  One out of order drops what was collected for that key, as SolixBLE does:
  a payload with a hole in it is worth less than waiting for the next.
  """
  def reassemble(buffers, key, payload) do
    # a first fragment always starts over
    parts = if match?(<<1::4, _::4, _::binary>>, payload), do: [], else: Map.get(buffers, key, [])

    case payload do
      <<index::4, total::4, data::binary>> when index == length(parts) + 1 and index <= total ->
        parts = parts ++ [data]

        if index == total,
          do: {:done, IO.iodata_to_binary(parts), Map.delete(buffers, key)},
          else: {:more, Map.put(buffers, key, parts)}

      _ ->
        {:more, Map.delete(buffers, key)}
    end
  end

  # -- parameters -------------------------------------------------------------------------

  @doc "Parameters from a list of `{key, bytes}`, in order."
  def params(list), do: for({key, value} <- list, into: <<>>, do: <<key, byte_size(value), value::binary>>)

  @doc """
  `%{key => bytes}` (type tag included) from a payload. Stops at the first
  field that does not fit, keeping what came before.
  """
  def parse_params(<<0x00, rest::binary>>), do: parse_fields(rest, %{})
  def parse_params(payload), do: parse_fields(payload, %{})

  defp parse_fields(<<key, len, value::binary-size(len), rest::binary>>, acc), do: parse_fields(rest, Map.put(acc, key, value))
  defp parse_fields(_, acc), do: acc

  @doc "An unsigned little-endian integer from a parameter, past its type tag."
  def uint(params, key) do
    case params do
      %{^key => <<_type, bytes::binary>>} when bytes != "" -> :binary.decode_unsigned(bytes, :little)
      _ -> nil
    end
  end

  @doc "A signed little-endian integer from a parameter, past its type tag."
  def int(params, key) do
    case params do
      %{^key => <<_type, bytes::binary>>} when bytes != "" ->
        n = bit_size(bytes)
        <<value::little-signed-size(^n)>> = bytes
        value

      _ ->
        nil
    end
  end

  @doc "Text from a parameter, past its type tag, without trailing NULs; `nil` if it is not text."
  def text(params, key) do
    with %{^key => <<_type, bytes::binary>>} <- params,
         text = String.trim_trailing(bytes, <<0>>),
         true <- text != "" and String.printable?(text) do
      text
    else
      _ -> nil
    end
  end

  # -- telemetry -------------------------------------------------------------------------

  @doc """
  A reading from telemetry parameters, in the C300 DC's layout (SolixBLE's
  `c300dc.py`), which the C200 DC shares: checked on the box against one
  battery at 100% and one at 16%. What a payload lacks is `nil`.

    * `charge` and `health`, % (`b7`, `b8`); `temp_c` (`b5`, signed)
    * `status`: `b6` as sent; SolixBLE reads 0 idle, 1 discharging,
      2 charging, not yet seen to hold on the C200
    * `watts_out`, `watts_in`: totals (`ad`, `ac`); `solar_w` (`ab`),
      `dc_w` (`aa`), `usb_w` per port (`a4` to `a9`)
    * `time_left_h`: to empty, or to full while charging (`a3`, tenths)
    * `capacity_mah`: what is left (`af`)
    * `firmware` (`b0`: 111 is "1.1.1"), `serial` (`c3`)
  """
  def telemetry(params) do
    %{
      charge: uint(params, 0xB7),
      health: uint(params, 0xB8),
      temp_c: int(params, 0xB5),
      status: uint(params, 0xB6),
      watts_out: uint(params, 0xAD),
      watts_in: uint(params, 0xAC),
      solar_w: uint(params, 0xAB),
      dc_w: uint(params, 0xAA),
      usb_w: %{
        c1: uint(params, 0xA4),
        c2: uint(params, 0xA5),
        c3: uint(params, 0xA6),
        c4: uint(params, 0xA7),
        a1: uint(params, 0xA8),
        a2: uint(params, 0xA9)
      },
      time_left_h: if(t = uint(params, 0xA3), do: t / 10),
      capacity_mah: uint(params, 0xAF),
      firmware: if(v = uint(params, 0xB0), do: v |> Integer.to_string() |> String.graphemes() |> Enum.join(".")),
      serial: text(params, 0xC3)
    }
  end

  @doc """
  The reading in a telemetry payload, or `nil` if it holds none. Plain
  first (the C200 DC); if that is not telemetry and the session has a
  `secret`, decrypted (the stations SolixBLE was written for).
  """
  def read_telemetry(payload, secret \\ nil) do
    with nil <- reading(parse_params(payload)),
         <<_::binary-32>> <- secret,
         {:ok, plain} <- decrypt(payload, secret) do
      reading(parse_params(plain))
    else
      %{} = reading -> reading
      _ -> nil
    end
  end

  # telemetry is a charge from 0 to 100; anything else is some other packet
  # or the wrong guess about encryption
  defp reading(params) do
    reading = telemetry(params)
    if is_integer(reading.charge) and reading.charge <= 100, do: reading
  end

  # -- the handshake ------------------------------------------------------------------------

  @doc "Our public key, as the station wants it: X and Y, no 04 prefix."
  def public_key do
    {<<4, xy::binary-64>>, _} = :crypto.generate_key(:ecdh, :secp256r1, @private_key)
    xy
  end

  @doc "The shared secret from the station's public key (X and Y, 64 bytes)."
  def shared_secret(<<_::binary-64>> = station_xy), do: :crypto.compute_key(:ecdh, <<4, station_xy::binary>>, @private_key, :secp256r1)

  @doc "The first packet: hello, with the time and who we are."
  def hello(now), do: packet(@negotiation, <<0x00, 0x01>>, params([{0xA1, ts(now)}, {0xA2, @client_uuid}]))

  @doc """
  What to send when the station answers negotiation `cmd`:
  `{:send, packet}`, `{:send, packet, secret}` (the session is encrypted
  from here), `:done` or `:unknown`.
  """
  def reply(cmd, params, now, tz \\ "UTC0")

  def reply(<<0x08, 0x01>>, _p, now, _tz),
    do: {:send, packet(@negotiation, <<0x00, 0x03>>, params([{0xA1, ts(now)}, {0xA2, @client_uuid}, {0xA3, <<0x20>>}, {0xA4, <<0x00, 0xF0>>}]))}

  def reply(<<0x08, 0x03>>, _p, now, _tz),
    do: {:send, packet(@negotiation, <<0x00, 0x29>>, params([{0xA1, ts(now)}, {0xA2, @client_uuid}]))}

  def reply(<<0x08, 0x29>>, _p, now, _tz),
    do:
      {:send,
       packet(@negotiation, <<0x00, 0x05>>, params([{0xA1, ts(now)}, {0xA2, @client_uuid}, {0xA3, <<0x20>>}, {0xA4, <<0x00, 0xF0>>}, {0xA5, <<0x40>>}]))}

  def reply(<<0x08, 0x05>>, _p, _now, _tz), do: {:send, packet(@negotiation, <<0x00, 0x21>>, params([{0xA1, public_key()}]))}

  def reply(<<0x08, 0x21>>, %{0xA1 => station_xy}, now, tz) when byte_size(station_xy) == 64 do
    secret = shared_secret(station_xy)
    payload = params([{0xA1, ts(now)}, {0xA2, @client_uuid}, {0xA3, <<0x20>>}, {0xA4, <<0, 0, 0, 0>>}, {0xA5, tz}])
    {:send, packet(@negotiation, <<0x40, 0x22>>, encrypt(payload, secret)), secret}
  end

  def reply(<<0x48, 0x22>>, _p, _now, _tz), do: :done
  def reply(_cmd, _p, _now, _tz), do: :unknown

  defp ts(unix_s), do: <<unix_s::little-32>>

  # -- the cipher -------------------------------------------------------------------------

  def encrypt(plain, <<key::binary-16, iv::binary-16>>),
    do: :crypto.crypto_one_time(:aes_128_cbc, key, iv, plain, encrypt: true, padding: :pkcs_padding)

  def decrypt(cipher, <<key::binary-16, iv::binary-16>>) do
    {:ok, :crypto.crypto_one_time(:aes_128_cbc, key, iv, cipher, encrypt: false, padding: :pkcs_padding)}
  rescue
    _ -> {:error, :decrypt}
  end

  # -- what a packet is ----------------------------------------------------------------------

  def negotiation?(%{pattern: p}), do: p == @negotiation
  def telemetry?(%{pattern: p, cmd: c}), do: p in @telemetry_patterns and (c in @telemetry_cmds or c == <<0x03, 0x00>>)
  @doc "A session packet, whatever its cmd (the C200 DC's telemetry is `0402`, in neither list above)."
  def session?(%{pattern: p}), do: p in @telemetry_patterns
  def encrypted_telemetry?(%{cmd: c} = pk), do: telemetry?(pk) and c in @telemetry_cmds
end
