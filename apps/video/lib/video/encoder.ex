defmodule Video.Encoder do
  @moduledoc """
  Which H.264 encoder to use and how to drive it. Hardware where it exists
  (VideoToolbox on a Mac, the V4L2 M2M block on a Pi), libx264 otherwise.
  Override with `config :video, encoder: "libx264"`.
  """

  @doc "Encoder name FFmpeg knows, chosen from what this ffmpeg was built with."
  def pick(ffmpeg \\ System.find_executable("ffmpeg")) do
    case Application.get_env(:video, :encoder) do
      nil ->
        have = encoders(ffmpeg)

        cond do
          "h264_videotoolbox" in have -> "h264_videotoolbox"
          "h264_v4l2m2m" in have -> "h264_v4l2m2m"
          "libx264" in have -> "libx264"
          true -> nil
        end

      name ->
        name
    end
  end

  @doc "Output-side arguments for an encoder at a bitrate, tuned for low delay."
  def args("h264_videotoolbox", kbps),
    do: ~w(-c:v h264_videotoolbox -realtime 1 -b:v #{kbps}k -maxrate #{kbps}k -bufsize #{kbps}k -pix_fmt yuv420p)

  def args("h264_v4l2m2m", kbps), do: ~w(-c:v h264_v4l2m2m -b:v #{kbps}k -pix_fmt yuv420p)

  def args("libx264", kbps),
    do: ~w(-c:v libx264 -preset veryfast -tune zerolatency -b:v #{kbps}k -maxrate #{kbps}k -bufsize #{kbps * 2}k -pix_fmt yuv420p)

  def args(other, kbps), do: ~w(-c:v #{other} -b:v #{kbps}k -pix_fmt yuv420p)

  defp encoders(nil), do: []

  defp encoders(ffmpeg) do
    case System.cmd(ffmpeg, ~w(-hide_banner -encoders), stderr_to_stdout: true) do
      {out, 0} -> Regex.scan(~r/^\s*V\S*\s+(\S+)/m, out, capture: :all_but_first) |> List.flatten()
      _ -> []
    end
  rescue
    _ -> []
  end
end
