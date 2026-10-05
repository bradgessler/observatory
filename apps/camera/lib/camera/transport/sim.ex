defmodule Camera.Transport.Sim do
  @moduledoc """
  A simulated Sony a6000 in PC Remote mode, speaking PTP the way the real one
  does: its device info, extended info and property blob are the bytes a real
  a6000 sent (`priv/sim/a6000`). Dials turn a notch per step, the shutter
  makes a picture that is ready after the exposure, and pictures come down from
  handle `0xFFFFC001` (two for RAW+JPEG). For tests and machines without a
  camera.

  Options:

    * `time_scale:` how fast simulated time runs against real exposures
      (default `0.0`: pictures are ready at once; `1.0` waits the full exposure);
    * `max_notches:` the most a dial moves per step command (default unlimited;
      a real a6000 sometimes moves fewer than asked);
    * `fail_after:` stop answering after this many transfers (a camera that
      wedges), to test the driver's recovery.
  """
  @behaviour Camera.Transport

  import Bitwise
  alias Camera.{Ptp, Sony}

  @handle 0xFFFFC001

  # the a6000's shutter dial, slowest first (bulb is past the slow end); Sony packs n/d as n << 16 | d
  @shutter Enum.map(
             [300, 250, 200, 150, 130, 100, 80, 60, 50, 40, 32, 25, 20, 16, 13, 10, 8, 6, 5, 4],
             &(&1 <<< 16 ||| 10)
           ) ++
             Enum.map(
               [
                 3,
                 4,
                 5,
                 6,
                 8,
                 10,
                 13,
                 15,
                 20,
                 25,
                 30,
                 40,
                 50,
                 60,
                 80,
                 100,
                 125,
                 160,
                 200,
                 250,
                 320,
                 400,
                 500,
                 640,
                 800,
                 1000,
                 1250,
                 1600,
                 2000,
                 2500,
                 3200,
                 4000
               ],
               &(1 <<< 16 ||| &1)
             )

  @doc "The shutter speeds this camera offers, slowest first, as Sony values."
  def shutter_speeds, do: @shutter

  defp dir, do: Path.join(:code.priv_dir(:camera), "sim/a6000")
  defp fixture(name), do: File.read!(Path.join(dir(), name))

  defp payload(name) do
    {:ok, %{payload: p}, _} = Ptp.parse(fixture(name))
    p
  end

  @impl true
  def open(opts) do
    {:ok, %{payload: blob}, _} = Ptp.parse(fixture("all_props_iso6400.bin"))

    {:ok,
     %{
       props: Sony.parse_props(blob),
       out: :queue.new(),
       session: nil,
       pending: nil,
       objects: [],
       ready_at: nil,
       shots: 0,
       transfers: 0,
       time_scale: Keyword.get(opts, :time_scale, 0.0),
       max_notches: Keyword.get(opts, :max_notches, :infinity),
       fail_after: Keyword.get(opts, :fail_after, :infinity),
       picture: fixture("moon.jpg")
     }}
  end

  @impl true
  def close(_), do: :ok

  @impl true
  def write(s, bin, _timeout) do
    s = %{s | transfers: s.transfers + 1}
    if s.transfers > s.fail_after, do: {:error, :timeout, s}, else: {:ok, take(s, bin)}
  end

  @impl true
  def read(s, max, _timeout) do
    s = %{s | transfers: s.transfers + 1}

    cond do
      s.transfers > s.fail_after ->
        {:error, :timeout, s}

      true ->
        case :queue.out(s.out) do
          {{:value, t}, rest} when byte_size(t) > max ->
            <<now::binary-size(^max), later::binary>> = t
            {:ok, now, %{s | out: :queue.in_r(later, rest)}}

          {{:value, t}, rest} ->
            {:ok, t, %{s | out: rest}}

          {:empty, _} ->
            {:error, :timeout, s}
        end
    end
  end

  @impl true
  def event(s, _timeout), do: {:none, s}

  # -- the camera's side of each transaction -----------------------------------------------------

  defp take(s, bin) do
    case Ptp.parse(bin) do
      {:ok, %{type: :command, code: op, tid: tid, payload: p}, _} ->
        params = Ptp.params(p)

        if op in [0x9205, 0x9207],
          do: %{s | pending: {op, tid, params}},
          else: answer(s, op, tid, params, nil)

      {:ok, %{type: :data, payload: data}, _} ->
        case s.pending do
          {op, tid, params} -> answer(%{s | pending: nil}, op, tid, params, data)
          nil -> s
        end

      _ ->
        s
    end
  end

  defp answer(s, op, tid, params, data) do
    {s, code, out} = handle(op, params, data, settle(s))
    s = if out, do: send_out(s, Ptp.container(:data, op, tid, out)), else: s
    send_out(s, Ptp.container(:response, Ptp.response_code(code), tid))
  end

  defp send_out(s, bin), do: %{s | out: :queue.in(bin, s.out)}

  # OpenSession, CloseSession, GetDeviceInfo, GetStorageIDs
  defp handle(0x1002, _, _, %{session: nil} = s), do: {%{s | session: 1}, :ok, nil}
  defp handle(0x1002, _, _, s), do: {s, :session_already_open, nil}
  defp handle(0x1003, _, _, s), do: {%{s | session: nil}, :ok, nil}
  defp handle(0x1001, _, _, s), do: {s, :ok, payload("device_info.bin")}
  defp handle(0x1004, _, _, s), do: {s, :ok, <<1::32-little, 0x00010001::32-little>>}

  # Sony: the handshake, the extended info, application priority, the property blob
  defp handle(0x9201, _, _, s), do: {s, :ok, <<0::64>>}
  defp handle(0x9202, _, _, s), do: {s, :ok, payload("ext_device_info.bin")}
  defp handle(0x9205, [code], data, s), do: {put_value(s, code, data), :ok, nil}
  defp handle(0x9209, _, _, s), do: {s, :ok, Sony.encode_props(s.props)}

  # the buttons and dials
  defp handle(0x9207, [0xD2C2], <<2::16-little>>, s), do: {shoot(s), :ok, nil}

  defp handle(0x9207, [code], <<_::16-little>>, s) when code in [0xD2C1, 0xD2C2],
    do: {s, :ok, nil}

  defp handle(0x9207, [code], <<steps::8-signed>>, s), do: {turn(s, code, steps), :ok, nil}

  # pictures in the camera's memory
  defp handle(0x1008, [@handle], _, %{objects: [o | _]} = s),
    do: {s, :ok, Ptp.encode_object_info(o.info)}

  defp handle(0x1009, [@handle], _, %{objects: [o | rest]} = s),
    do: {set_in_memory(%{s | objects: rest}, length(rest)), :ok, o.bytes}

  defp handle(op, _, _, s) when op in [0x1008, 0x1009], do: {s, :invalid_object_handle, nil}

  defp handle(_, _, _, s), do: {s, :operation_not_supported, nil}

  defp put_value(s, code, data) do
    case s.props[code] do
      %{type: t} = d ->
        with(
          {v, _} <- Ptp.value(t, data),
          do: put_in(s.props[code], %{d | current: v}),
          else: (_ -> s)
        )

      _ ->
        s
    end
  end

  # a dial: ISO walks its list, the shutter walks @shutter (+1 is faster), others ignore it
  defp turn(s, code, steps) do
    n =
      if s.max_notches == :infinity,
        do: steps,
        else: steps |> max(-s.max_notches) |> min(s.max_notches)

    case s.props[code] do
      %{form: {:enum, vals}, current: cur} = d ->
        i = Enum.find_index(vals, &(&1 == cur)) || 0

        put_in(s.props[code], %{
          d
          | current: Enum.at(vals, (i + n) |> max(0) |> min(length(vals) - 1))
        })

      %{name: :shutter, current: cur} = d ->
        ladder = [0 | @shutter]
        i = Enum.find_index(ladder, &(&1 == cur)) || 0

        put_in(s.props[code], %{
          d
          | current: Enum.at(ladder, (i + n) |> max(0) |> min(length(ladder) - 1))
        })

      _ ->
        s
    end
  end

  # the full press: a picture (two with RAW+JPEG), ready once the exposure is over
  defp shoot(s) do
    n = s.shots + 1

    seconds =
      case Sony.shutter_seconds(s.props[0xD20D].current) do
        :bulb -> 1.0
        x -> x
      end

    jpeg = %{
      info: %{
        storage_id: 0x00010001,
        format: :jpeg,
        size: byte_size(s.picture),
        width: 6000,
        height: 4000,
        filename: "DSC0#{n + 1000}.JPG"
      },
      bytes: s.picture
    }

    raw_bytes = "ARW simulated raw " <> Integer.to_string(n)

    arw = %{
      info: %{
        storage_id: 0x00010001,
        format: :arw,
        size: byte_size(raw_bytes),
        width: 6000,
        height: 4000,
        filename: "DSC0#{n + 1000}.ARW"
      },
      bytes: raw_bytes
    }

    files = if s.props[0x5004].current == 19, do: [jpeg, arw], else: [jpeg]

    %{
      s
      | shots: n,
        objects: [],
        ready_at:
          {System.monotonic_time(:millisecond) + round(seconds * 1000 * s.time_scale), files}
    }
  end

  # time passes: a picture whose exposure has ended shows up in memory
  defp settle(%{ready_at: {at, files}} = s) do
    if System.monotonic_time(:millisecond) >= at,
      do: set_in_memory(%{s | objects: files, ready_at: nil}, length(files)),
      else: s
  end

  defp settle(s), do: s

  defp set_in_memory(s, 0), do: put_in(s.props[0xD215].current, 0)
  defp set_in_memory(s, n), do: put_in(s.props[0xD215].current, 0x8000 + n)
end
