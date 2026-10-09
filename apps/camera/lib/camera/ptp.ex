defmodule Camera.Ptp do
  @moduledoc """
  PTP (ISO 15740), the protocol stills cameras speak over USB. Pure: bytes in,
  terms out; a transport carries them (`Camera.Transport`).

  Everything is a container: a little-endian header (length, type, code,
  transaction id) and a payload.

    * a **command** names an operation and up to five 32-bit parameters;
    * an optional **data** phase carries a dataset one way or the other;
    * a **response** says how it went (`0x2001` is OK) with its own parameters;
    * **events** arrive on their own (an interrupt endpoint).

  A transaction (`transact/4`) is one command, its data phase if any, and its
  response, all with one transaction id. Datasets the camera sends back are
  read with `device_info/1`, `object_info/1` and `value/2`.
  """

  import Bitwise

  @command 1
  @data 2
  @response 3
  @event 4

  @doc "Container types by name."
  def type(:command), do: @command
  def type(:data), do: @data
  def type(:response), do: @response
  def type(:event), do: @event

  @ops %{
    get_device_info: 0x1001,
    open_session: 0x1002,
    close_session: 0x1003,
    get_storage_ids: 0x1004,
    get_object_info: 0x1008,
    get_object: 0x1009,
    get_device_prop_desc: 0x1014,
    get_device_prop_value: 0x1015
  }

  @doc "An operation code by name."
  def op(name), do: Map.fetch!(@ops, name)

  @responses %{
    0x2001 => :ok,
    0x2002 => :general_error,
    0x2003 => :session_not_open,
    0x2004 => :invalid_transaction_id,
    0x2005 => :operation_not_supported,
    0x2006 => :parameter_not_supported,
    0x2007 => :incomplete_transfer,
    0x2009 => :invalid_object_handle,
    0x200A => :device_prop_not_supported,
    0x2019 => :device_busy,
    0x201D => :invalid_parameter,
    0x201E => :session_already_open,
    0x201F => :transaction_cancelled
  }

  @doc "A response code in words (`:ok`, `:device_busy`, ...), or `{:unknown, code}`."
  def response(code), do: Map.get(@responses, code, {:unknown, code})

  @doc "The response code for a word (the simulator answers with these)."
  def response_code(word), do: Enum.find_value(@responses, fn {c, w} -> if w == word, do: c end)

  # -- containers --------------------------------------------------------------------------------

  @doc "One container: header and payload."
  def container(type, code, tid, payload \\ <<>>) do
    <<12 + byte_size(payload)::32-little, type(type)::16-little, code::16-little, tid::32-little,
      payload::binary>>
  end

  @doc "A command container: the operation and its parameters (32 bits each, at most five)."
  def command(op, tid, params \\ []) when length(params) <= 5 do
    container(:command, op, tid, for(p <- params, into: <<>>, do: <<p::32-little>>))
  end

  @doc """
  The first container in `bin`: `{:ok, %{type, code, tid, payload}, rest}`, or
  `{:more, bytes_still_needed}` when it hasn't all arrived.
  """
  def parse(<<len::32-little, type::16-little, code::16-little, tid::32-little, _::binary>> = bin)
      when len >= 12 do
    if byte_size(bin) >= len do
      body = len - 12
      <<_::binary-size(12), payload::binary-size(^body), rest::binary>> = bin
      {:ok, %{type: type_name(type), code: code, tid: tid, payload: payload}, rest}
    else
      {:more, len - byte_size(bin)}
    end
  end

  def parse(<<len::32-little, _::binary>>) when len < 12, do: {:error, :bad_length}
  def parse(bin), do: {:more, 12 - byte_size(bin)}

  @doc "The 32-bit parameters of a command, response or event payload."
  def params(payload), do: for(<<p::32-little <- payload>>, do: p)

  defp type_name(@command), do: :command
  defp type_name(@data), do: :data
  defp type_name(@response), do: :response
  defp type_name(@event), do: :event
  defp type_name(other), do: {:unknown, other}

  # -- transactions ------------------------------------------------------------------------------

  defmodule Conn do
    @moduledoc "A transport and where the transaction ids are."
    defstruct [:transport, :state, tid: 0, session: nil, timeout: 10_000, chunk: 1_048_576]
  end

  @doc """
  One transaction: send the command (and `data:` if given), read the data the
  camera sends back (`read: true`), then its response.

  Returns `{:ok, %{code, words, params, data}, conn}`; `code` is the response
  word (`:ok` on success). A transport failure is `{:error, reason, conn}`.
  `timeout:` bounds each USB transfer (default the connection's).
  """
  def transact(%Conn{} = conn, op, params \\ [], opts \\ []) do
    timeout = Keyword.get(opts, :timeout, conn.timeout)
    tid = if op == op(:open_session), do: 0, else: conn.tid + 1
    conn = %{conn | tid: tid}

    with {:ok, conn} <- write(conn, command(op, tid, params), timeout),
         {:ok, conn} <- maybe_send(conn, op, tid, opts[:data], timeout),
         {:ok, first, conn} <- read_mine(conn, tid, timeout) do
      case first do
        %{type: :data, payload: data} ->
          with {:ok, resp, conn} <- read_mine(conn, tid, timeout), do: answer(resp, data, conn)

        %{type: :response} = resp ->
          answer(resp, nil, conn)

        other ->
          {:error, {:unexpected, other.type}, conn}
      end
    end
  end

  defp maybe_send(conn, _op, _tid, nil, _timeout), do: {:ok, conn}

  defp maybe_send(conn, op, tid, data, timeout),
    do: write(conn, container(:data, op, tid, data), timeout)

  defp answer(%{type: :response, code: code, payload: payload}, data, conn) do
    {:ok, %{code: response(code), raw: code, params: params(payload), data: data}, conn}
  end

  defp answer(other, _data, conn), do: {:error, {:unexpected, other.type}, conn}

  defp write(%Conn{transport: t, state: s} = conn, bin, timeout) do
    case t.write(s, bin, timeout) do
      {:ok, s} -> {:ok, %{conn | state: s}}
      {:error, reason, s} -> {:error, reason, %{conn | state: s}}
    end
  end

  # A container for this transaction: one left over from an earlier, interrupted transaction (a
  # program that died mid-way, a cancelled read) carries another id, and is dropped, not answered.
  defp read_mine(conn, tid, timeout, dropped \\ 0)
  defp read_mine(conn, _tid, _timeout, dropped) when dropped > 8, do: {:error, :out_of_step, conn}

  defp read_mine(conn, tid, timeout, dropped) do
    case read_container(conn, timeout) do
      {:ok, %{tid: ^tid} = c, conn} -> {:ok, c, conn}
      {:ok, _stale, conn} -> read_mine(conn, tid, timeout, dropped + 1)
      error -> error
    end
  end

  @doc """
  Read and drop whatever is waiting in the bulk-in pipe (answers to an earlier,
  interrupted conversation), so the next transaction starts clean. Returns the
  connection and how many bytes were thrown away.
  """
  def drain(%Conn{transport: t} = conn, dropped \\ 0) do
    case t.read(conn.state, conn.chunk, 100) do
      {:ok, <<>>, s} ->
        {%{conn | state: s}, dropped}

      {:ok, bytes, s} when dropped < 64_000_000 ->
        drain(%{conn | state: s}, dropped + byte_size(bytes))

      {:ok, _, s} ->
        {%{conn | state: s}, dropped}

      {:error, _, s} ->
        {%{conn | state: s}, dropped}
    end
  end

  # One container from the bulk-in pipe: the first transfer carries its length; the rest arrive
  # as pieces, kept as a list and joined once (joining as they come is quadratic: a 25 MB RAW in
  # 64 KB pieces would copy gigabytes on a Pi). An empty transfer (the zero-length packet after a
  # payload that filled its last packet) is skipped.
  defp read_container(conn, timeout), do: read_head(conn, <<>>, timeout, 0)

  defp read_head(conn, _acc, _timeout, empties) when empties > 3, do: {:error, :no_data, conn}

  defp read_head(%Conn{transport: t, state: s, chunk: chunk} = conn, acc, timeout, empties) do
    case t.read(s, chunk, timeout) do
      {:ok, <<>>, s} ->
        read_head(%{conn | state: s}, acc, timeout, empties + 1)

      {:ok, bytes, s} ->
        head = acc <> bytes
        conn = %{conn | state: s}

        case parse(head) do
          {:ok, c, _rest} ->
            {:ok, c, conn}

          {:more, _} when byte_size(head) < 12 ->
            read_head(conn, head, timeout, 0)

          {:more, _} ->
            read_rest(
              conn,
              binary_part(head, 0, 4) |> :binary.decode_unsigned(:little),
              [head],
              byte_size(head),
              timeout
            )

          {:error, reason} ->
            {:error, reason, conn}
        end

      {:error, reason, s} ->
        {:error, reason, %{conn | state: s}}
    end
  end

  defp read_rest(conn, len, pieces, have, _timeout) when have >= len do
    {:ok, c, _rest} = parse(pieces |> Enum.reverse() |> IO.iodata_to_binary())
    {:ok, c, conn}
  end

  defp read_rest(%Conn{transport: t, state: s, chunk: chunk} = conn, len, pieces, have, timeout) do
    case t.read(s, min(len - have, chunk), timeout) do
      {:ok, <<>>, s} ->
        read_rest(%{conn | state: s}, len, pieces, have, timeout)

      {:ok, bytes, s} ->
        read_rest(%{conn | state: s}, len, [bytes | pieces], have + byte_size(bytes), timeout)

      {:error, reason, s} ->
        {:error, reason, %{conn | state: s}}
    end
  end

  @doc "An event from the interrupt pipe, if one comes within `timeout`: `{:ok, %{code, params}, conn}` or `{:none, conn}`."
  def event(%Conn{transport: t, state: s} = conn, timeout \\ 10) do
    case t.event(s, timeout) do
      {:ok, bytes, s} ->
        case parse(bytes) do
          {:ok, %{type: :event, code: code, payload: p}, _} ->
            {:ok, %{code: code, params: params(p)}, %{conn | state: s}}

          _ ->
            {:none, %{conn | state: s}}
        end

      {:none, s} ->
        {:none, %{conn | state: s}}

      {:error, reason, s} ->
        {:error, reason, %{conn | state: s}}
    end
  end

  # -- datasets ----------------------------------------------------------------------------------

  @doc "A PTP string: a count of UTF-16 code units (with the terminating zero), then the units."
  def string(<<0, rest::binary>>), do: {"", rest}

  def string(<<n, rest::binary>>) do
    k = n * 2
    <<units::binary-size(^k), rest::binary>> = rest

    text =
      units |> :unicode.characters_to_binary({:utf16, :little}) |> String.trim_trailing(<<0>>)

    {text, rest}
  end

  @doc "A string as PTP sends it."
  def encode_string(""), do: <<0>>

  def encode_string(text) do
    units = :unicode.characters_to_binary(text <> <<0>>, :utf8, {:utf16, :little})
    <<div(byte_size(units), 2), units::binary>>
  end

  @doc "An array of 16-bit values: a 32-bit count, then the values."
  def array16(<<n::32-little, rest::binary>>) do
    k = n * 2
    <<vals::binary-size(^k), rest::binary>> = rest
    {for(<<v::16-little <- vals>>, do: v), rest}
  end

  @doc "An array of 32-bit values: a 32-bit count, then the values."
  def array32(<<n::32-little, rest::binary>>) do
    k = n * 4
    <<vals::binary-size(^k), rest::binary>> = rest
    {for(<<v::32-little <- vals>>, do: v), rest}
  end

  @doc "What the camera says it is and can do (GetDeviceInfo)."
  def device_info(payload) do
    <<std::16-little, vendor::32-little, vendor_version::16-little, rest::binary>> = payload
    {vendor_desc, rest} = string(rest)
    <<mode::16-little, rest::binary>> = rest
    {ops, rest} = array16(rest)
    {events, rest} = array16(rest)
    {props, rest} = array16(rest)
    {capture, rest} = array16(rest)
    {image, rest} = array16(rest)
    {manufacturer, rest} = string(rest)
    {model, rest} = string(rest)
    {version, rest} = string(rest)
    {serial, _rest} = string(rest)

    %{
      standard_version: std,
      vendor_extension_id: vendor,
      vendor_extension_version: vendor_version,
      vendor_extension_desc: vendor_desc,
      functional_mode: mode,
      operations: ops,
      events: events,
      properties: props,
      capture_formats: capture,
      image_formats: image,
      manufacturer: manufacturer,
      model: model,
      device_version: version,
      serial_number: serial
    }
  end

  @formats %{
    0x3001 => :association,
    0x3801 => :jpeg,
    0x3800 => :undefined_image,
    0xB101 => :arw,
    0x3000 => :undefined
  }

  @doc "An object format code in a word (`:jpeg`, `:arw`, ...), else the code."
  def format(code), do: Map.get(@formats, code, code)

  @doc "What an object is (GetObjectInfo): its format, size, name and pixel size."
  def object_info(payload) do
    <<storage::32-little, fmt::16-little, protection::16-little, size::32-little,
      thumb_fmt::16-little, thumb_size::32-little, thumb_w::32-little, thumb_h::32-little,
      w::32-little, h::32-little, depth::32-little, parent::32-little, assoc_type::16-little,
      assoc_desc::32-little, seq::32-little, rest::binary>> = payload

    {filename, rest} = string(rest)
    {captured, rest} = string(rest)
    {modified, rest} = if rest == <<>>, do: {"", rest}, else: string(rest)
    {keywords, _} = if rest == <<>>, do: {"", rest}, else: string(rest)

    %{
      storage_id: storage,
      format: format(fmt),
      protection: protection,
      size: size,
      thumb_format: format(thumb_fmt),
      thumb_size: thumb_size,
      thumb_width: thumb_w,
      thumb_height: thumb_h,
      width: w,
      height: h,
      bit_depth: depth,
      parent: parent,
      association_type: assoc_type,
      association_desc: assoc_desc,
      sequence: seq,
      filename: filename,
      capture_date: captured,
      modification_date: modified,
      keywords: keywords
    }
  end

  @doc "The same, as a camera would send it (for the simulator)."
  def encode_object_info(i) do
    <<i.storage_id::32-little, format_code(i.format)::16-little, 0::16-little, i.size::32-little,
      format_code(i[:thumb_format] || 0)::16-little, i[:thumb_size] || 0::32-little, 0::32-little,
      0::32-little, i.width::32-little, i.height::32-little, i[:bit_depth] || 0::32-little,
      0::32-little, 0::16-little, 0::32-little, 0::32-little>> <>
      encode_string(i.filename) <>
      encode_string(i[:capture_date] || "") <> encode_string("") <> encode_string("")
  end

  defp format_code(code) when is_integer(code), do: code

  defp format_code(word),
    do: Enum.find_value(@formats, 0x3000, fn {c, w} -> if w == word, do: c end)

  # -- property values ---------------------------------------------------------------------------

  @types %{
    0x0001 => :int8,
    0x0002 => :uint8,
    0x0003 => :int16,
    0x0004 => :uint16,
    0x0005 => :int32,
    0x0006 => :uint32,
    0x0007 => :int64,
    0x0008 => :uint64,
    0xFFFF => :string
  }

  @doc "A data type code in a word (`:uint16`, `:string`, ...)."
  def data_type(code), do: Map.get(@types, code, {:unknown, code})

  @doc "The code for a data type word."
  def data_type_code(word), do: Enum.find_value(@types, fn {c, w} -> if w == word, do: c end)

  @doc "One value of `type` from the front of `bin`: `{value, rest}`, or `:error` when it isn't there."
  def value(:int8, <<v::8-signed, rest::binary>>), do: {v, rest}
  def value(:uint8, <<v::8, rest::binary>>), do: {v, rest}
  def value(:int16, <<v::16-little-signed, rest::binary>>), do: {v, rest}
  def value(:uint16, <<v::16-little, rest::binary>>), do: {v, rest}
  def value(:int32, <<v::32-little-signed, rest::binary>>), do: {v, rest}
  def value(:uint32, <<v::32-little, rest::binary>>), do: {v, rest}
  def value(:int64, <<v::64-little-signed, rest::binary>>), do: {v, rest}
  def value(:uint64, <<v::64-little, rest::binary>>), do: {v, rest}
  def value(:string, <<_, _::binary>> = bin), do: string(bin)
  def value(_, _), do: :error

  @doc "A value as the camera expects it."
  def encode_value(:int8, v), do: <<v::8-signed>>
  def encode_value(:uint8, v), do: <<v &&& 0xFF::8>>
  def encode_value(:int16, v), do: <<v::16-little-signed>>
  def encode_value(:uint16, v), do: <<v::16-little>>
  def encode_value(:int32, v), do: <<v::32-little-signed>>
  def encode_value(:uint32, v), do: <<v::32-little>>
  def encode_value(:int64, v), do: <<v::64-little-signed>>
  def encode_value(:uint64, v), do: <<v::64-little>>
  def encode_value(:string, v), do: encode_string(v)
end
