defmodule Camera.Sony do
  @moduledoc """
  Sony's remote control over PTP ("PC Remote" in the camera's USB Connection
  menu), on top of `Camera.Ptp`. Written for the a6000 and its generation
  (protocol 2.00, "for models earlier than 2020"); the facts come from
  libgphoto2 and from traces of a real a6000.

  **Connecting** is OpenSession, then Sony's three-step SDIO handshake with
  the extended device info in between, then asking for application priority so
  the computer's settings win over the dials.

  **Settings** live in one blob (`0x9209`) of property descriptions: code, type,
  whether it can be changed, its default and current value, and the values it
  may take. On these cameras ISO, shutter speed and aperture can't be set
  outright: the computer turns the dial, a notch at a time (`ControlDevice`
  with a signed step), and reads the blob again to see where it landed.
  `set/4` does that until the value matches, overshoots, or stops moving.

  **Capturing** is pressing the button: half, full, release full, release
  half; then waiting until the camera says a picture is waiting in its memory
  (`ObjectInMemory` at `0x8000` or more), and downloading it from the fixed
  handle `0xFFFFC001`, once per file (RAW+JPEG gives two).
  """

  import Bitwise
  alias Camera.Ptp

  @sdio_connect 0x9201
  @ext_device_info 0x9202
  @set_ext_prop 0x9205
  @control_device 0x9207
  @all_props 0x9209
  @protocol_200 0xC8

  @in_memory_handle 0xFFFFC001

  @props %{
    quality: 0x5004,
    white_balance: 0x5005,
    f_number: 0x5007,
    focus_mode: 0x500A,
    metering: 0x500B,
    flash: 0x500C,
    exposure_program: 0x500E,
    exposure_compensation: 0x5010,
    drive_mode: 0x5013,
    shutter: 0xD20D,
    focus_found: 0xD213,
    object_in_memory: 0xD215,
    battery: 0xD218,
    iso: 0xD21E,
    priority_mode: 0xD25A,
    shutter_half: 0xD2C1,
    shutter_full: 0xD2C2
  }

  @doc "A property code by name (`:iso`, `:shutter`, `:object_in_memory`, ...)."
  def prop(name), do: Map.fetch!(@props, name)

  @doc "The name of a property code, else the code."
  def prop_name(code), do: Enum.find_value(@props, code, fn {n, c} -> if c == code, do: n end)

  # -- the property blob -------------------------------------------------------------------------

  @doc """
  Every property in a `0x9209` blob: `%{code => %{code, type, getset, enabled,
  default, current, form}}`, where `form` is `{:enum, values}`, `{:range, min,
  max, step}` or `:none`.
  """
  def parse_props(<<_count::32-little, _::32-little, rest::binary>>), do: parse_dpds(rest, %{})
  def parse_props(_), do: %{}

  defp parse_dpds(<<code::16-little, type::16-little, getset, enabled, rest::binary>>, acc) do
    t = Ptp.data_type(type)

    with {default, rest} <- Ptp.value(t, rest),
         {current, rest} <- Ptp.value(t, rest) do
      {form, rest} = parse_form(t, rest)

      d = %{
        code: code,
        name: prop_name(code),
        type: t,
        getset: getset,
        enabled: enabled,
        default: default,
        current: current,
        form: form,
        order: map_size(acc)
      }

      parse_dpds(rest, Map.put(acc, code, d))
    else
      _ -> acc
    end
  end

  defp parse_dpds(_, acc), do: acc

  defp parse_form(t, <<1, rest::binary>>) do
    with {lo, rest} <- Ptp.value(t, rest),
         {hi, rest} <- Ptp.value(t, rest),
         {st, rest} <- Ptp.value(t, rest) do
      {{:range, lo, hi, st}, rest}
    else
      _ -> {:none, <<>>}
    end
  end

  defp parse_form(t, <<2, n::16-little, rest::binary>>) do
    {vals, rest} = take_values(t, rest, n, [])

    # newer bodies (2024) follow with the values that can be set, when the next word isn't a property code
    case rest do
      <<m::16-little, more::binary>> when m < 0x200 and m > 0 ->
        {settable, rest} = take_values(t, more, m, [])
        {{:enum, settable}, rest}

      _ ->
        {{:enum, vals}, rest}
    end
  end

  defp parse_form(_t, <<0, rest::binary>>), do: {:none, rest}
  defp parse_form(_t, rest), do: {:none, rest}

  defp take_values(_t, rest, 0, acc), do: {Enum.reverse(acc), rest}

  defp take_values(t, rest, n, acc) do
    case Ptp.value(t, rest) do
      {v, rest} -> take_values(t, rest, n - 1, [v | acc])
      :error -> {Enum.reverse(acc), rest}
    end
  end

  @doc "The blob as the camera sends it (the simulator answers with this): inverse of `parse_props/1`."
  def encode_props(props) do
    dpds =
      props
      |> Map.values()
      |> Enum.sort_by(&{&1[:order] || 0, &1.code})
      |> Enum.map(&encode_dpd/1)

    <<map_size(props)::32-little, 0::32-little>> <> IO.iodata_to_binary(dpds)
  end

  defp encode_dpd(%{code: code, type: t} = d) do
    [
      <<code::16-little, Ptp.data_type_code(t)::16-little, d.getset, d.enabled>>,
      Ptp.encode_value(t, d.default),
      Ptp.encode_value(t, d.current),
      case d.form do
        {:enum, vals} ->
          [<<2, length(vals)::16-little>> | Enum.map(vals, &Ptp.encode_value(t, &1))]

        {:range, lo, hi, st} ->
          [<<1>>, Ptp.encode_value(t, lo), Ptp.encode_value(t, hi), Ptp.encode_value(t, st)]

        :none ->
          <<0>>
      end
    ]
  end

  # -- connecting --------------------------------------------------------------------------------

  @doc """
  Open the session and do Sony's handshake. Returns `{:ok, info, conn}` with
  the device info plus `:sony_version` (200 on an a6000) and the extra
  property and operation codes the camera admitted to.
  """
  def connect(%Ptp.Conn{} = conn) do
    # answers left from an earlier, interrupted conversation would put every reply one step behind
    {conn, _dropped} = Ptp.drain(conn)

    with {:ok, %{code: c}, conn} when c in [:ok, :session_already_open] <-
           Ptp.transact(conn, Ptp.op(:open_session), [1]),
         conn = %{conn | session: 1},
         {:ok, %{code: :ok, data: di}, conn} <-
           Ptp.transact(conn, Ptp.op(:get_device_info), [], read: true),
         info = Ptp.device_info(di),
         {:ok, _, conn} <- Ptp.transact(conn, @sdio_connect, [1, 0, 0], read: true),
         {:ok, _, conn} <- Ptp.transact(conn, @sdio_connect, [2, 0, 0], read: true),
         {:ok, ext, conn} <- ext_info(conn, 20),
         {:ok, _, conn} <- Ptp.transact(conn, @sdio_connect, [3, 0, 0], read: true),
         {:ok, _, conn} <-
           Ptp.transact(conn, @set_ext_prop, [prop(:priority_mode)],
             data: Ptp.encode_value(:int8, 1)
           ) do
      {:ok, Map.merge(info, ext), conn}
    else
      {:ok, %{code: code}, conn} -> {:error, {:refused, code}, conn}
      {:error, reason, conn} -> {:error, reason, conn}
    end
  end

  # the camera may answer empty for a moment after the second handshake step
  defp ext_info(conn, 0), do: {:ok, %{sony_version: nil, sony_props: [], sony_ops: []}, conn}

  defp ext_info(conn, tries) do
    case Ptp.transact(conn, @ext_device_info, [@protocol_200], read: true) do
      {:ok, %{code: :ok, data: <<version::16-little, rest::binary>>}, conn} ->
        {codes, rest} = Ptp.array16(rest)
        {more, _} = if byte_size(rest) >= 4, do: Ptp.array16(rest), else: {[], rest}
        all = codes ++ more

        {:ok,
         %{
           sony_version: version,
           sony_props: Enum.filter(all, &((&1 &&& 0x7000) == 0x5000)),
           sony_ops: Enum.filter(all, &((&1 &&& 0x7000) == 0x1000))
         }, conn}

      {:ok, _, conn} ->
        Process.sleep(50)
        ext_info(conn, tries - 1)

      error ->
        error
    end
  end

  @doc "Close the session (the camera returns to its own control)."
  def disconnect(conn) do
    case Ptp.transact(conn, Ptp.op(:close_session)) do
      {:ok, _, conn} -> {:ok, conn}
      {:error, _, conn} -> {:ok, conn}
    end
  end

  # -- settings ----------------------------------------------------------------------------------

  @doc "Every property, read fresh: `{:ok, %{code => description}, conn}`."
  def props(conn) do
    case Ptp.transact(conn, @all_props, [], read: true) do
      {:ok, %{code: :ok, data: data}, conn} when is_binary(data) -> {:ok, parse_props(data), conn}
      {:ok, %{code: code}, conn} -> {:error, {:refused, code}, conn}
      error -> error
    end
  end

  @doc "Turn a dial `steps` notches (negative is the other way). The camera moves when it's ready; read back to see."
  def step(conn, prop_code, steps) when steps != 0 do
    reply(Ptp.transact(conn, @control_device, [prop_code], data: Ptp.encode_value(:uint8, steps)))
  end

  @doc "Press or release a button property: `2` down, `1` up."
  def press(conn, prop_code, value) do
    reply(
      Ptp.transact(conn, @control_device, [prop_code], data: Ptp.encode_value(:uint16, value))
    )
  end

  defp reply({:ok, %{code: :ok}, conn}), do: {:ok, conn}
  defp reply({:ok, %{code: code}, conn}), do: {:error, {:refused, code}, conn}
  defp reply(error), do: error

  @doc """
  Set a property by turning its dial until it reads `target`.

  Where the property lists its values, the first turn jumps the whole way,
  then single notches correct it (the camera lists values it won't always take,
  so a big jump can land beside the target). Without a list, `order:` (a
  function from value to a number that grows in the dial's `+1` direction)
  says which way to turn. Each turn is read back for up to `settle_ms`
  (3000). Stops when the value matches, when it passes the target (that value
  isn't available: the nearest one is kept), when a turn changes nothing, or
  after 60 turns.

  Returns `{:ok, value_it_landed_on, conn}`.
  """
  def set(conn, prop_code, target, opts \\ []) do
    with {:ok, props, conn} <- props(conn), %{} = d <- Map.get(props, prop_code) do
      if d.current == target, do: {:ok, target, conn}, else: turn(conn, d, target, opts, 60, true)
    else
      nil -> {:error, :no_such_property, conn}
      error -> error
    end
  end

  defp turn(conn, d, _target, _opts, 0, _first), do: {:ok, d.current, conn}

  defp turn(conn, d, target, opts, tries, first) do
    {pos_now, pos_want} = positions(d, target, opts)

    cond do
      pos_want == nil ->
        {:error, :not_a_value, conn}

      pos_now == pos_want ->
        {:ok, d.current, conn}

      true ->
        delta = pos_want - pos_now
        steps = if first and match?({:enum, _}, d.form), do: delta, else: sign(delta)
        steps = steps |> max(-127) |> min(127)

        with {:ok, conn} <- step(conn, d.code, steps),
             {:ok, d2, conn} <- await_change(conn, d, Keyword.get(opts, :settle_ms, 3000)) do
          {pos_after, _} = positions(d2, target, opts)

          cond do
            d2.current == target ->
              {:ok, target, conn}

            # the a6000 sometimes ignores a notch: ask again (twice) before calling it the end of the dial
            d2.current == d.current and Keyword.get(opts, :retried, 0) < 2 ->
              turn(
                conn,
                d2,
                target,
                Keyword.update(opts, :retried, 1, &(&1 + 1)),
                tries - 1,
                false
              )

            d2.current == d.current ->
              {:ok, d2.current, conn}

            sign(pos_want - pos_after) != sign(delta) and pos_after != pos_want ->
              {:ok, d2.current, conn}

            true ->
              turn(conn, d2, target, Keyword.delete(opts, :retried), tries - 1, false)
          end
        end
    end
  end

  defp positions(%{form: {:enum, vals}} = d, target, opts) do
    case {Enum.find_index(vals, &(&1 == d.current)), Enum.find_index(vals, &(&1 == target))} do
      {nil, _} -> positions(%{d | form: :none}, target, opts)
      found -> found
    end
  end

  defp positions(d, target, opts) do
    order = Keyword.get(opts, :order, & &1)
    {order.(d.current), order.(target)}
  end

  defp await_change(conn, d, ms) do
    deadline = System.monotonic_time(:millisecond) + ms
    await_change(conn, d, deadline, 0)
  end

  defp await_change(conn, d, deadline, n) do
    with {:ok, props, conn} <- props(conn) do
      d2 = Map.get(props, d.code, d)

      if d2.current != d.current or System.monotonic_time(:millisecond) >= deadline do
        {:ok, d2, conn}
      else
        Process.sleep(if n < 3, do: 100, else: 200)
        await_change(conn, d, deadline, n + 1)
      end
    end
  end

  defp sign(x) when x > 0, do: 1
  defp sign(x) when x < 0, do: -1
  defp sign(_), do: 0

  # -- capturing ---------------------------------------------------------------------------------

  @doc """
  Take one picture and download everything it made (RAW+JPEG is two files).

  Options: `exposure_ms:` how long the shutter will be open (the wait for the
  picture allows for it; default 1000), `wait_ms:` how long after that to wait
  for the camera to have it ready (35000).

  Returns `{:ok, [%{name, format, bytes, info, pressed_at, pressed_mono, ready_at, settings}],
  conn}`: `pressed_at` is when the shutter press was sent, `ready_at` when the camera had the
  picture (both UTC), `pressed_mono` is the press by this VM's monotonic clock in ms (for
  measuring against other things that happened here, whatever the wall clock did), and
  `settings` is what the camera was set to as the shutter was pressed (`describe/1`: ISO,
  shutter speed, quality), read just before the press.
  """
  def capture(conn, opts \\ []) do
    with {:ok, props, conn} <- drain_memory(conn, 4),
         # what this picture is taken at: a dial turned while it comes down belongs to the next
         settings = describe(props),
         {:ok, conn} <- press(conn, prop(:shutter_half), 2),
         pressed = DateTime.utc_now(),
         pressed_mono = System.monotonic_time(:millisecond),
         {:ok, conn} <- press(conn, prop(:shutter_full), 2),
         {:ok, conn} <- hold_for_focus(conn),
         {:ok, conn} <- press(conn, prop(:shutter_full), 1),
         {:ok, conn} <- press(conn, prop(:shutter_half), 1),
         {:ok, conn} <-
           await_picture(
             conn,
             Keyword.get(opts, :exposure_ms, 1000) + Keyword.get(opts, :wait_ms, 35_000)
           ),
         ready = DateTime.utc_now(),
         {:ok, files, conn} <- download_all(conn, []) do
      # when the box pressed the shutter and when the camera had the picture: the exposure sits
      # just after the first (a manual-focus camera opens within tens of ms of the press)
      stamps = %{
        pressed_at: pressed,
        pressed_mono: pressed_mono,
        ready_at: ready,
        settings: settings
      }

      {:ok, Enum.map(files, &Map.merge(&1, stamps)), conn}
    end
  end

  # A picture left in the camera's memory from before would come down as this one: clear it first.
  # Hands on the properties as it last read them: how the camera is set as the shutter is pressed.
  defp drain_memory(conn, tries) do
    with {:ok, props, conn} <- props(conn) do
      case current(props, :object_in_memory) do
        n when is_integer(n) and n >= 0x8000 and tries > 0 ->
          with {:ok, _, conn} <- download(conn), do: drain_memory(conn, tries - 1)

        _ ->
          {:ok, props, conn}
      end
    end
  end

  # autofocus wants the button held until focus is found (up to a second); manual focus doesn't wait
  defp hold_for_focus(conn) do
    with {:ok, props, conn} <- props(conn) do
      if current(props, :focus_mode) == 1,
        do: {:ok, conn},
        else: wait_focus(conn, System.monotonic_time(:millisecond) + 1000)
    end
  end

  defp wait_focus(conn, deadline) do
    with {:ok, props, conn} <- props(conn) do
      if current(props, :focus_found) in [2, 3] or System.monotonic_time(:millisecond) >= deadline,
        do: {:ok, conn},
        else: Process.sleep(50) && wait_focus(conn, deadline)
    end
  end

  defp await_picture(conn, ms),
    do: await_picture(conn, System.monotonic_time(:millisecond) + ms, 0)

  defp await_picture(conn, deadline, n) do
    with {:ok, props, conn} <- props(conn) do
      cond do
        (current(props, :object_in_memory) || 0) >= 0x8000 ->
          {:ok, conn}

        System.monotonic_time(:millisecond) >= deadline ->
          {:error, :no_picture, conn}

        true ->
          Process.sleep(if n < 10, do: 100, else: 250) && await_picture(conn, deadline, n + 1)
      end
    end
  end

  defp download_all(conn, acc) do
    with {:ok, props, conn} <- props(conn) do
      if (current(props, :object_in_memory) || 0) >= 0x8000 and length(acc) < 4 do
        with {:ok, file, conn} <- download(conn), do: download_all(conn, [file | acc])
      else
        {:ok, Enum.reverse(acc), conn}
      end
    end
  end

  defp download(conn) do
    with {:ok, %{code: :ok, data: oi}, conn} <-
           Ptp.transact(conn, Ptp.op(:get_object_info), [@in_memory_handle], read: true),
         info = Ptp.object_info(oi),
         {:ok, %{code: :ok, data: bytes}, conn} <-
           Ptp.transact(conn, Ptp.op(:get_object), [@in_memory_handle],
             read: true,
             timeout: 30_000
           ) do
      {:ok, %{name: info.filename, format: info.format, bytes: bytes, info: info}, conn}
    else
      {:ok, %{code: code}, conn} -> {:error, {:refused, code}, conn}
      error -> error
    end
  end

  defp current(props, name), do: get_in(props, [prop(name), :current])

  # -- what the values mean ----------------------------------------------------------------------

  @doc "ISO in words: a number, or `:auto` (`0xFFFFFF`)."
  def iso(0xFFFFFF), do: :auto
  def iso(v), do: v

  @doc "Shutter speed in seconds (a float), or `:bulb`. Sony packs it as numerator << 16 | denominator."
  def shutter_seconds(0), do: :bulb

  def shutter_seconds(v) do
    num = v >>> 16
    den = v &&& 0xFFFF
    if den == 0, do: :bulb, else: num / den
  end

  @doc "Shutter speed as a photographer writes it: \"1/200\", \"1\", \"2.5\", \"30\", or \"Bulb\"."
  def shutter_words(0), do: "Bulb"

  def shutter_words(v) do
    num = v >>> 16
    den = v &&& 0xFFFF

    cond do
      den == 0 -> "Bulb"
      num == 1 and den > 1 -> "1/#{den}"
      rem(num, den) == 0 -> "#{div(num, den)}"
      true -> :erlang.float_to_binary(num / den, decimals: 1)
    end
  end

  @doc "The Sony value for a shutter speed given as seconds or \"1/200\"-style words."
  def shutter_value("Bulb"), do: 0

  def shutter_value(words) when is_binary(words) do
    case String.split(words, "/") do
      [n, d] -> String.to_integer(n) <<< 16 ||| String.to_integer(d)
      [s] -> shutter_value(String.to_float(if String.contains?(s, "."), do: s, else: s <> ".0"))
    end
  end

  def shutter_value(seconds) when is_number(seconds) and seconds >= 1,
    do: round(seconds * 10) <<< 16 ||| 10

  def shutter_value(seconds) when is_number(seconds) and seconds >= 0.3,
    do: round(seconds * 10) <<< 16 ||| 10

  def shutter_value(seconds) when is_number(seconds), do: 1 <<< 16 ||| round(1 / seconds)

  @doc "Image quality in words."
  def quality(2), do: "JPEG Standard"
  def quality(3), do: "JPEG Fine"
  def quality(4), do: "JPEG Extra Fine"
  def quality(16), do: "RAW"
  def quality(19), do: "RAW+JPEG"
  def quality(v), do: "#{v}"

  @doc """
  The settings that matter, in plain terms, from a property map: `%{iso,
  shutter, shutter_s, f_number, quality, focus, program, battery}`.
  """
  def describe(props) do
    v = fn name -> current(props, name) end

    %{
      iso: v.(:iso) && iso(v.(:iso)),
      isos:
        case get_in(props, [prop(:iso), :form]) do
          {:enum, vals} -> Enum.map(vals, &iso/1)
          _ -> []
        end,
      shutter: v.(:shutter) && shutter_words(v.(:shutter)),
      shutter_s: v.(:shutter) && shutter_seconds(v.(:shutter)),
      f_number: v.(:f_number) && v.(:f_number) / 100,
      quality: v.(:quality) && quality(v.(:quality)),
      focus:
        case v.(:focus_mode) do
          1 -> :manual
          nil -> nil
          _ -> :auto
        end,
      program: v.(:exposure_program),
      battery: v.(:battery),
      in_memory: v.(:object_in_memory)
    }
  end
end
