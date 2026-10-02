defmodule Input.HIDRaw do
  @moduledoc """
  Game pads on Linux with no C helper: the kernel already exposes every HID
  device as `/dev/hidrawN`, with its identity and report descriptor in sysfs.
  `list/0` reads those; `open/2` reads reports straight from the device file.

  The reader speaks the same messages as `Input.HIDPort`'s port (`"O "` once
  open, `"R <hex>"` per report, `{:exit_status, _}` when the device goes), so
  `Input.Device` does not know which one it has. Unplugging ends the read
  with an error, the reader says so and exits, and the device process ends;
  `Input.Discovery` finds the pad again when it is plugged back in.

  A Pi has no libhidapi; a Mac has no `/dev/hidraw`. So: this on Linux,
  `Input.HIDPort` elsewhere (`Input.Discovery`).
  """
  import Bitwise

  @sys "/sys/class/hidraw"

  @doc "Is this a Linux kernel with hidraw?"
  def available?, do: File.dir?(@sys)

  @doc "Every HID device the kernel exposes, in `Input.HIDPort.list/0`'s shape."
  def list do
    for dir <- Path.wildcard(Path.join(@sys, "hidraw*")) |> Enum.sort(), dev = describe(dir), do: dev
  end

  defp describe(dir) do
    uevent = dir |> Path.join("device/uevent") |> File.read!() |> parse_uevent()
    [_bus, vid, pid] = String.split(uevent["HID_ID"], ":")
    {page, usage} = dir |> Path.join("device/report_descriptor") |> File.read!() |> top_usage()

    %{
      vendor_id: String.to_integer(vid, 16),
      product_id: String.to_integer(pid, 16),
      usage_page: page,
      usage: usage,
      path: "/dev/" <> Path.basename(dir),
      manufacturer: "",
      product: uevent["HID_NAME"] || ""
    }
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end

  defp parse_uevent(text) do
    for line <- String.split(text, "\n", trim: true), [k, v] <- [String.split(line, "=", parts: 2)], into: %{}, do: {k, v}
  end

  @doc """
  The usage page and usage of a device's first application collection, from
  its report descriptor: what the device says it is (1/4 joystick, 1/5 game
  pad, 1/6 keyboard, 1/2 mouse). Short items only, which is all the top of a
  descriptor holds.
  """
  def top_usage(descriptor), do: walk(descriptor, nil, nil)

  defp walk(<<prefix, rest::binary>>, page, usage) do
    size = case prefix &&& 0x3 do
      3 -> 4
      n -> n
    end

    case rest do
      <<data::little-size(^size)-unit(8), tail::binary>> ->
        case prefix &&& 0xFC do
          # Usage Page (global)
          0x04 -> walk(tail, data, usage)
          # Usage (local): the first one before the collection names it
          0x08 -> walk(tail, page, usage || data)
          # Collection: the application's own usage is settled by now
          0xA0 -> {page || 0, usage || 0}
          _ -> walk(tail, page, usage)
        end

      _ ->
        {page || 0, usage || 0}
    end
  end

  defp walk(_, page, usage), do: {page || 0, usage || 0}

  @doc """
  Read reports from `path` in a process linked to `owner`, which receives
  `{pid, {:data, {:eol, "O " <> path}}}` once open, then
  `{pid, {:data, {:eol, "R " <> hex}}}` per report, and
  `{pid, {:exit_status, 1}}` when the device goes. Reads one input report
  at a time, its length from the device's report descriptor.
  """
  def open(path, owner \\ self()) do
    spawn_link(fn -> read(path, owner, report_bytes(path)) end)
  end

  defp read(path, owner, bytes) do
    case File.open(path, [:read, :binary, :raw]) do
      {:ok, fd} ->
        send(owner, {self(), {:data, {:eol, "O " <> path}}})
        loop(fd, owner, bytes)

      {:error, why} ->
        send(owner, {self(), {:data, {:eol, "E cannot open #{path}: #{inspect(why)}"}}})
    end
  end

  # Exactly one report per read. hidraw hands back one report per read(2),
  # but Erlang's file read keeps reading until it has every byte asked for:
  # ask for more than a report and reports arrive glued together, dozens at
  # a time and late, and no parser can read them. A pulled cable ends the
  # read with an error (or end of file).
  defp loop(fd, owner, bytes) do
    case :file.read(fd, bytes) do
      {:ok, report} ->
        send(owner, {self(), {:data, {:eol, "R " <> Base.encode16(report, case: :lower)}}})
        loop(fd, owner, bytes)

      _gone ->
        send(owner, {self(), {:exit_status, 1}})
    end
  end

  @doc "A device's input report length in bytes, from its report descriptor in sysfs."
  def report_bytes("/dev/" <> name) do
    case File.read(Path.join([@sys, name, "device/report_descriptor"])) do
      {:ok, descriptor} -> report_length(descriptor)
      _ -> 64
    end
  end

  def report_bytes(_), do: 64

  @doc """
  The length of an input report, from a report descriptor: the bits of every
  Input item (Report Size × Report Count, as the globals stand at it), per
  report id, rounded up to bytes, plus the id byte when there are ids. With
  several ids the longest wins (game pads have one). 64 when it cannot tell.
  """
  def report_length(descriptor) do
    case items(descriptor, %{size: 0, count: 0, id: nil}, %{}) do
      bits when map_size(bits) == 0 -> 64
      %{nil => b} = bits when map_size(bits) == 1 -> div(b + 7, 8)
      bits -> (bits |> Map.values() |> Enum.max() |> Kernel.+(7) |> div(8)) + 1
    end
  end

  defp items(<<prefix, rest::binary>>, g, bits) do
    size = case prefix &&& 0x3 do
      3 -> 4
      n -> n
    end

    case rest do
      <<data::little-size(^size)-unit(8), tail::binary>> ->
        case prefix &&& 0xFC do
          # Report Size, Report Count, Report ID (globals)
          0x74 -> items(tail, %{g | size: data}, bits)
          0x94 -> items(tail, %{g | count: data}, bits)
          0x84 -> items(tail, %{g | id: data}, bits)
          # Input (main): these bits are in the report
          0x80 -> items(tail, g, Map.update(bits, g.id, g.size * g.count, &(&1 + g.size * g.count)))
          _ -> items(tail, g, bits)
        end

      _ ->
        bits
    end
  end

  defp items(_, _g, bits), do: bits
end
