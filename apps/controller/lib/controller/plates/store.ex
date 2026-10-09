defmodule Controller.Plates.Store do
  @moduledoc """
  Where plates live between restarts: one directory per session under
  `~/.observatory/plates` (`config :controller, :plates_dir` elsewhere), the
  photos as they arrived and a `session.json` with every plate's record;
  `current.json` says which session each mount is on.

      ~/.observatory/plates/
        current.json                          {"eq6r": "eq6r-20260925T211403-4f2a"}
        eq6r-20260925T211403-4f2a/
          session.json
          photo-1.jpg  photo-2.jpg  ...

  A session that is started over stays on disk: the photos of a night are
  worth having the next day, when a solve that failed can be looked at.
  Files are written whole and renamed into place, so a crash mid-write
  leaves the previous version, never half of one.

  (Plain files while there is one kind of record here. When sessions and
  plates want querying, this is the module that becomes an Ecto repo.)
  """

  require Logger

  def dir, do: Application.get_env(:controller, :plates_dir) || Path.join([System.user_home!(), ".observatory", "plates"])

  @doc "A fresh session id for a mount: readable, sortable, unique."
  def new_id(mount, now \\ DateTime.utc_now()) do
    safe = mount |> to_string() |> String.downcase() |> String.replace(~r/[^a-z0-9]+/, "-") |> String.trim("-")
    stamp = Calendar.strftime(now, "%Y%m%dT%H%M%S")
    "#{safe}-#{stamp}-#{:crypto.strong_rand_bytes(2) |> Base.encode16(case: :lower)}"
  end

  @doc "Every mount's current session, as saved: `%{mount => session}`. Unreadable files are skipped, with a warning."
  def load do
    with {:ok, bin} <- File.read(Path.join(dir(), "current.json")),
         {:ok, current} when is_map(current) <- Jason.decode(bin) do
      for {mount, sid} <- current, is_binary(sid), session = load_session(sid), into: %{}, do: {mount, session}
    else
      {:error, :enoent} -> %{}
      other ->
        Logger.warning("plates: current.json unreadable (#{inspect(other)}); starting empty")
        %{}
    end
  end

  defp load_session(sid) do
    with {:ok, bin} <- File.read(session_path(sid)), {:ok, map} <- Jason.decode(bin) do
      from_json(map)
    else
      other ->
        Logger.warning("plates: session #{sid} unreadable (#{inspect(other)}); skipped")
        nil
    end
  end

  @doc "Save one session and point its mount at it."
  def save(%{id: sid, mount: mount} = session) do
    File.mkdir_p!(Path.join(dir(), sid))
    write!(session_path(sid), Jason.encode!(to_json(session), pretty: true))

    current =
      with {:ok, bin} <- File.read(Path.join(dir(), "current.json")),
           {:ok, map} when is_map(map) <- Jason.decode(bin) do
        map
      else
        _ -> %{}
      end

    if current[mount] != sid, do: write!(Path.join(dir(), "current.json"), Jason.encode!(Map.put(current, mount, sid), pretty: true))
    :ok
  end

  @doc "Keep a photo's bytes; returns the file name (relative to the session)."
  def put_image(sid, n, bytes, ext) do
    File.mkdir_p!(Path.join(dir(), sid))
    name = "photo-#{n}#{ext}"
    write!(Path.join([dir(), sid, name]), bytes)
    name
  end

  def image_path(sid, name), do: Path.join([dir(), sid, name])

  def delete_image(sid, name), do: File.rm(image_path(sid, name))

  defp session_path(sid), do: Path.join([dir(), sid, "session.json"])

  defp write!(path, bytes) do
    tmp = path <> ".tmp"
    File.write!(tmp, bytes)
    File.rename!(tmp, path)
  end

  # -- records <-> JSON ------------------------------------------------------------------

  @doc false
  def to_json(s) do
    %{
      "id" => s.id,
      "mount" => s.mount,
      "home_at" => s.home_at,
      "next" => s.next,
      "applied" => s.applied,
      "created_at" => iso(s.created_at),
      "plates" => Enum.map(s.plates, &plate_json/1)
    }
  end

  defp plate_json(p) do
    %{
      "n" => p.n,
      "state" => Atom.to_string(p.state),
      "reason" => p.reason,
      "moving" => p.moving,
      "file" => p.file,
      "captured_at" => iso(p.captured_at),
      "photo_at" => iso(p.photo_at),
      "at" => iso(p.at),
      "time_from" => p.time_from,
      "enc" => p.enc && Map.new(p.enc, fn {k, v} -> {Atom.to_string(k), v} end),
      "tracking" => p.tracking,
      "homed_at" => p.homed_at,
      "hint" => p.hint && Map.new(p.hint, fn {k, v} -> {Atom.to_string(k), v} end),
      "scale" => (case p[:scale] do {lo, hi} -> [lo, hi]; _ -> nil end),
      "min_stars" => p[:min_stars],
      "timeout" => p[:timeout],
      "queued_at" => iso(p.queued_at),
      "attempts" => p.attempts,
      "solution" => p.solution && Map.new(p.solution, fn {k, v} -> {Atom.to_string(k), v} end)
    }
  end

  @doc false
  def from_json(m) do
    %{
      id: m["id"],
      mount: m["mount"],
      home_at: m["home_at"],
      next: m["next"] || 1,
      applied: m["applied"] == true,
      created_at: time(m["created_at"]),
      plates: Enum.map(m["plates"] || [], &plate_from/1)
    }
  end

  @enc ~w(ra_deg dec_deg ra_steps dec_steps ra_running dec_running)
  @hint ~w(ra_deg dec_deg radius_deg)
  @solution ~w(ra_deg dec_deg width_deg height_deg rotation_deg parity seconds solver stars pixscale_arcsec)

  defp plate_from(m) do
    %{
      n: m["n"],
      state: state(m["state"]),
      reason: m["reason"],
      moving: m["moving"] == true,
      file: m["file"],
      captured_at: time(m["captured_at"]),
      photo_at: time(m["photo_at"]),
      at: time(m["at"]),
      time_from: m["time_from"],
      enc: pick(m["enc"], @enc),
      tracking: m["tracking"] == true,
      homed_at: m["homed_at"],
      hint: pick(m["hint"], @hint),
      scale: (case m["scale"] do [lo, hi] -> {lo, hi}; _ -> nil end),
      min_stars: m["min_stars"],
      timeout: m["timeout"],
      queued_at: time(m["queued_at"]),
      started_ms: nil,
      attempts: m["attempts"] || 0,
      solution: pick(m["solution"], @solution)
    }
  end

  defp state("queued"), do: :queued
  defp state("solving"), do: :solving
  defp state("solved"), do: :solved
  defp state(_), do: :failed

  defp pick(nil, _), do: nil
  defp pick(map, keys), do: for(k <- keys, Map.has_key?(map, k), into: %{}, do: {String.to_atom(k), map[k]})

  defp iso(nil), do: nil
  defp iso(%DateTime{} = t), do: DateTime.to_iso8601(t)

  defp time(nil), do: nil

  defp time(s) do
    case DateTime.from_iso8601(s) do
      {:ok, t, _} -> t
      _ -> nil
    end
  end
end
