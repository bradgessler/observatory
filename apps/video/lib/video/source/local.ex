defmodule Video.Source.Local do
  @moduledoc """
  A camera on this machine: AVFoundation on macOS, V4L2 on Linux. Device
  discovery and mode listing both go through ffmpeg itself so there is no
  second tool to install.
  """
  @behaviour Video.Source

  @impl true
  def devices do
    case {os(), ffmpeg()} do
      {_, nil} ->
        []

      {:darwin, bin} ->
        {out, _} = System.cmd(bin, ~w(-hide_banner -f avfoundation -list_devices true -i), stderr_to_stdout: true)

        out
        |> String.split("\n")
        |> Enum.drop_while(&(not String.contains?(&1, "video devices")))
        |> Enum.take_while(&(not String.contains?(&1, "audio devices")))
        |> Enum.flat_map(fn line ->
          case Regex.run(~r/\[(\d+)\]\s+(.+)$/, line) do
            [_, idx, name] -> [%{id: idx, name: String.trim(name)}]
            _ -> []
          end
        end)

      {:linux, _} ->
        "/dev/video*" |> Path.wildcard() |> Enum.map(&%{id: &1, name: &1})

      _ ->
        []
    end
  end

  # On a Mac, ask for an impossible size and ffmpeg prints what the device
  # does support. Linux would need v4l2-ctl; say :unknown and let it try.
  @impl true
  def modes(device) do
    case {os(), ffmpeg()} do
      {:darwin, bin} ->
        args = ~w(-hide_banner -nostdin -f avfoundation -video_size 7x7 -i #{(device || "0") <> ":none"} -t 0.1 -f null -)
        {out, _} = System.cmd(bin, args, stderr_to_stdout: true)

        case Regex.scan(~r/(\d{3,4})x(\d{3,4})@/, out, capture: :all_but_first) do
          [] -> :unknown
          sizes -> sizes |> Enum.map(fn [w, h] -> {String.to_integer(w), String.to_integer(h)} end) |> Enum.uniq()
        end

      _ ->
        :unknown
    end
  rescue
    _ -> :unknown
  end

  @impl true
  def input_args(device, {w, h}) do
    case os() do
      # Ask for nv12 explicitly. Left to itself avfoundation picks uyvy422 and
      # then, if any output names a pixel format, tries to honour *that* on
      # the input, fails, and hands over frames with the wrong stride — the
      # "inside a black hole" picture. nv12 is what VideoToolbox wants anyway.
      :darwin ->
        ~w(-f avfoundation -framerate 30 -pixel_format nv12 -video_size #{w}x#{h} -capture_cursor 0 -i #{(device || "0") <> ":none"})

      :linux ->
        ~w(-f v4l2 -input_format mjpeg -framerate 30 -video_size #{w}x#{h} -i #{device || "/dev/video0"})

      _ ->
        []
    end
  end

  defp os do
    case :os.type() do
      {:unix, :darwin} -> :darwin
      {:unix, _} -> :linux
      _ -> :other
    end
  end

  defp ffmpeg, do: System.find_executable("ffmpeg")
end
