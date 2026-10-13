defmodule Controller.StillCamera.Record do
  @moduledoc """
  Everything the box knows about one picture from the stills camera, read
  from what it wrote beside the picture's files: the sidecar (`<name>.json`:
  the camera's settings, the mount at shutter open and close, where it
  pointed, the site, the optics, the timings, the stars measured, each file's
  size and hash), the plate solve's answer (`<name>.solve.json`) when one was
  asked for, and whether the files are still on this machine's card or have
  been collected.

      Record.read(231)
      #=> %{seq: 231, night: "2026-10-13", name: "20261013-093624-DSC01003",
      #     sidecar: %{"camera" => ..., "mount" => ..., "time" => ...},
      #     solve: %{"state" => "solved", "solution" => ...} | nil,
      #     files: [%{name: "…ARW", format: "arw", bytes: 24_600_000, sha256: "…", here: true}]}

  A picture is known by its number (`seq`, what the roll calls it). The
  newest record with that number wins: the count starts again when the box
  is switched on with no roll to pick up from.

  Read only, and from files: nothing here asks the camera's process, so a
  page can be opened on a picture while the next one is being taken.
  """

  alias Controller.StillCamera

  @doc "The record of picture `seq`, or nil when no sidecar has been written for it (it is still being taken, or it failed)."
  def read(seq) when is_integer(seq) do
    with {night, name} <- locate(seq),
         dir = Path.join(StillCamera.dir(), night),
         {:ok, json} <- File.read(Path.join(dir, name <> ".json")),
         {:ok, sidecar} <- Jason.decode(json) do
      %{
        seq: seq,
        night: night,
        name: name,
        sidecar: sidecar,
        solve: solve(dir, name),
        files: for(f <- sidecar["files"] || [], do: %{name: f["name"], format: f["format"], bytes: f["bytes"], sha256: f["sha256"], here: File.regular?(Path.join(dir, f["name"] || ""))})
      }
    else
      _ -> nil
    end
  end

  def read(_), do: nil

  @doc "Which night's folder and which file name hold picture `seq`: `{night, name}` or nil. The newest nights are looked in first."
  def locate(seq) do
    dir = StillCamera.dir()

    nights =
      case File.ls(dir) do
        {:ok, names} -> names |> Enum.filter(&(&1 =~ ~r/^\d{4}-\d{2}-\d{2}$/)) |> Enum.sort(:desc) |> Enum.take(2)
        _ -> []
      end

    Enum.find_value(nights, fn night ->
      case File.read(Path.join([dir, night, "index.jsonl"])) do
        {:ok, index} -> in_index(index, seq) |> then(&(&1 && {night, &1}))
        _ -> nil
      end
    end)
  end

  # the last line of a night's index with this number: its first file's name without the extension
  defp in_index(index, seq) do
    needle = ~s("seq":#{seq})

    index
    |> String.split("\n", trim: true)
    |> Enum.reverse()
    |> Enum.find_value(fn line ->
      with true <- String.contains?(String.replace(line, " ", ""), needle),
           {:ok, %{"seq" => ^seq, "files" => [%{"name" => file} | _]}} <- Jason.decode(line) do
        Path.rootname(file)
      else
        _ -> nil
      end
    end)
  end

  defp solve(dir, name) do
    with {:ok, json} <- File.read(Path.join(dir, name <> ".solve.json")), {:ok, map} <- Jason.decode(json), do: map, else: (_ -> nil)
  end
end
