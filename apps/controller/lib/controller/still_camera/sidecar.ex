defmodule Controller.StillCamera.Sidecar do
  @moduledoc """
  Everything known about a stills picture when it was taken, kept in a JSON
  file beside it (`20261003-162024-DSC00001.json` next to the `.ARW` and the
  `.JPG`). The camera's own files are never opened for writing: no tag goes
  into the RAW or the JPEG, and each file's SHA-256 is in the sidecar so that
  can be checked later. One line per picture is also added to the night's
  `index.jsonl`, the same record, so a night can be read without opening
  every file.

  What is in it (`"schema": "observatory.still/1"`):

    * `time`: when the box pressed the shutter, when the exposure ended
      (that plus the shutter speed), when the camera had the picture, when it
      was saved. UTC, from the box's clock.
    * `files`: each file as saved: name, the camera's own name, bytes, SHA-256.
    * `camera`: model, ISO, shutter, quality, focus mode, battery, as they
      were when the shutter was pressed (`settings_from`: `"shutter"`; or
      `"status"`, when the driver could only say what they were afterwards).
    * `optics`: focal length and aperture, when they've been set, and where
      the focal length came from (`focal_length_from`): `"solve"` once a
      plate solve has measured it (`Controller.StillCamera.Optics`; the label
      it took the place of is `focal_length_label_mm`), `"label"` until then.
    * `mount`: the mount at the exposure's start and end (both axes: degrees,
      encoder steps, rate, running; tracking; homed) and its `track` between
      them, sampled four times a second.
    * `settling`: true when the shutter opened within `settle.settle_s`
      seconds of the mount's last slew (`settle.since_slew_s` after it; 0 when
      the mount slewed with the shutter open). The first picture after a slew
      is often poor: it is kept, and not counted.
    * `cloud` and `transparency`: how much of their light the stars have
      against the clearest picture of this field so far (1.0 is as clear as
      it has been), and `cloud: true` when they are more than 20 percent
      dimmer while the sky is brighter, or gone under a far brighter sky
      (`Controller.StillCamera.Cloud`). `transparency_from` says how many
      stars that is from and how bright the sky was against that picture's.
      Left out when the picture has no stars to say. A picture through cloud
      is kept, and not counted.
    * `pointing`: where the model says the scope pointed (RA/Dec, alt/az), and
      which model said so. Absent when the mount isn't homed or lined up.
    * `model`, `site`, `box`: the alignment in force, the site, which box and
      firmware.
    * `lock_on`: whether Lock On was holding, its rates, how far off the
      target was, and the calibration it was steering by (pixels per second
      of picture for each motor, and the drift), which is also the picture's
      scale and orientation against the mount's axes.
    * `measured`: what the box found in the small grey copy, and `star_size`:
      how wide the stars are (the median half-flux diameter of `n` stars, in
      `arcsec` and in `px` of a copy `w` wide; `Controller.StillCamera.Focus`).
      Left out when the picture had no stars to measure.
    * `plate_solve`: when pictures are being plate solved, which plate this one
      became and the file its answer is written to (`<name>.solve.json`: RA/Dec
      of the centre, field, rotation; or why it wasn't solved).

  It is as good as what was known that night: a mount that isn't homed has no
  RA/Dec, and the encoder positions are still there to work it out later.
  """

  alias Controller.ScopeCamera.Header
  alias Controller.Sky.Astro
  alias Controller.Settings
  alias Controller.StillCamera.Optics

  @schema "observatory.still/1"
  @sample_ms 250

  # -- the mount, watched while a picture is taken ----------------------------------------------

  @doc "Start sampling mount `id` (every 250 ms) until `stop/1`. `nil` in, `nil` out."
  def watch(nil), do: nil

  def watch(id) do
    Task.async(fn -> sample(id, [{DateTime.utc_now(), Header.snapshot(id)}]) end)
  end

  @doc "Stop sampling: `[{utc, snapshot}]`, oldest first."
  def stop(nil), do: []

  def stop(%Task{pid: pid} = task) do
    send(pid, :stop)
    Task.await(task, 5_000)
  catch
    :exit, _ -> []
  end

  defp sample(id, acc) do
    receive do
      :stop -> Enum.reverse([{DateTime.utc_now(), Header.snapshot(id)} | acc])
    after
      @sample_ms -> sample(id, [{DateTime.utc_now(), Header.snapshot(id)} | acc])
    end
  end

  # -- the record -------------------------------------------------------------------------------

  @doc """
  The record for one picture. `shot` is what `Controller.StillCamera` knows:
  `seq`, `saved_at`, `pressed_at`, `ready_at`, `files` (`[%{name, camera_name,
  format, bytes, sha256}]`), `camera` (`Camera.status/1`), `settings` (the
  camera's, as read when the shutter was pressed), `mount_id`, `samples`
  (from `stop/1`), `settle` (`%{settling, since_slew_s, settle_s}`), `sky`
  (`Controller.StillCamera.Cloud.judge/3`'s verdict), `lock`
  (`Controller.LockOn.status/0`), `calibration` (the mount's saved one),
  `measured`. Anything missing is left out.
  """
  def build(shot) do
    camera = shot[:camera] || %{}
    # the settings the picture was taken at; without those, the camera's as it says now, and said to be so
    {settings, settings_from} = if is_map(shot[:settings]), do: {shot[:settings], "shutter"}, else: {camera[:settings] || %{}, camera[:settings] && "status"}
    exposure_s = seconds(settings[:shutter])
    pressed = shot[:pressed_at] || shot[:saved_at]
    ended = if exposure_s, do: DateTime.add(pressed, round(exposure_s * 1000), :millisecond), else: pressed
    ctx = Header.context(shot[:mount_id], pressed)

    plain(%{
      schema: @schema,
      seq: shot[:seq],
      time: %{
        shutter_pressed: pressed,
        exposure_end: ended,
        exposure_s: exposure_s,
        picture_ready: shot[:ready_at],
        saved: shot[:saved_at],
        # a box that has just booted keeps its own time until the network sets it: times written then can be off by a minute
        clock: if(Controller.Clock.synced?(), do: "set by the network", else: "the box's own, not yet set by the network"),
        note: "UTC by the box's clock. shutter_pressed is when the box sent the press; the camera opens within tens of ms."
      },
      files: shot[:files],
      camera: %{
        id: camera[:id],
        model: camera[:model],
        manufacturer: camera[:manufacturer],
        iso: settings[:iso],
        shutter: settings[:shutter],
        exposure_s: exposure_s,
        quality: settings[:quality],
        f_number: settings[:f_number],
        focus: settings[:focus],
        battery_pct: settings[:battery],
        settings_from: settings_from
      },
      optics: optics(),
      mount: mount(shot[:mount_id], shot[:samples] || [], pressed, ended),
      settling: shot[:settle] && shot.settle[:settling],
      settle: shot[:settle] && Map.take(shot.settle, [:since_slew_s, :settle_s]),
      cloud: shot[:sky] && shot.sky[:cloud],
      transparency: shot[:sky] && shot.sky[:transparency],
      transparency_from: if(is_map(shot[:sky]) and shot.sky[:cloud] != nil, do: Map.take(shot.sky, [:stars, :sky_ratio, :first])),
      pointing: pointing(ctx[:pointing], ctx[:site], pressed),
      model: ctx[:model],
      site: ctx[:site],
      lock_on: lock(shot[:lock], shot[:calibration]),
      measured: shot[:measured],
      plate_solve: plate(shot[:plate], Path.basename(to_string(shot[:files] |> List.first() |> Map.get(:name))) |> Path.rootname()),
      box: %{node: ctx[:node], firmware: ctx[:firmware]}
    })
  end

  @doc "Write the record beside the picture and add it to the night's index. Returns the sidecar's path."
  def write(night, base, record) do
    path = Path.join(night, base <> ".json")
    File.write!(path, Jason.encode_to_iodata!(record, pretty: true))
    File.write!(Path.join(night, "index.jsonl"), [Jason.encode_to_iodata!(record), "\n"], [:append])
    path
  end

  @doc "A shutter speed as the camera words it (`\"1/60\"`, `\"4\"`, `\"2.5\"`) in seconds, or nil (`\"Bulb\"`)."
  def seconds(s) when is_number(s), do: s * 1.0

  def seconds(s) when is_binary(s) do
    case String.split(s, "/") do
      [n, d] -> with {n, ""} <- Float.parse(n), {d, ""} <- Float.parse(d), true <- d > 0, do: n / d, else: (_ -> nil)
      [n] -> with {n, ""} <- Float.parse(n), do: n, else: (_ -> nil)
      _ -> nil
    end
  end

  def seconds(_), do: nil

  # the focal length in force and whether a plate solve measured it or it is the label's
  defp optics do
    focal = Optics.focal_length() || %{}
    %{focal_length_mm: focal[:mm], focal_length_from: focal[:from], focal_length_label_mm: focal[:label_mm], aperture_mm: Settings.get("aperture_mm")}
  end

  # the mount at the exposure's two ends, and the samples between them
  defp mount(nil, _, _, _), do: nil

  defp mount(id, samples, pressed, ended) do
    samples = Enum.filter(samples, fn {_, snap} -> is_map(snap) end)
    during = Enum.filter(samples, fn {t, _} -> DateTime.diff(t, pressed, :millisecond) >= -400 and DateTime.diff(t, ended, :millisecond) <= 400 end)

    %{
      id: id,
      start: nearest(samples, pressed),
      end: nearest(samples, ended),
      track: Enum.map(during, fn {t, snap} -> Map.put(axes(snap), :at, t) end)
    }
  end

  defp nearest([], _), do: nil

  defp nearest(samples, at) do
    {t, snap} = Enum.min_by(samples, fn {t, _} -> abs(DateTime.diff(t, at, :millisecond)) end)
    snap |> Map.take([:connected, :tracking, :homed]) |> Map.merge(axes(snap)) |> Map.put(:at, t)
  end

  defp axes(snap) do
    for axis <- [:ra, :dec], a = get_in(snap, [:axes, axis]), is_map(a), into: %{} do
      {axis, %{deg: a[:degrees], steps: a[:steps], deg_per_s: a[:deg_per_s], running: a[:running]}}
    end
  end

  defp pointing({ra, dec, source}, site, at) when is_number(ra) and is_number(dec) do
    altaz =
      if is_number(site[:lat]) and is_number(site[:lon]),
        do: Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(at, site.lon))

    base = %{ra_deg: ra, dec_deg: dec, equinox: 2000.0, source: source}

    case altaz do
      {alt, az} -> Map.merge(base, %{alt_deg: alt, az_deg: az})
      _ -> base
    end
  end

  defp pointing(_, _, _), do: nil

  # handed to the plate solver: which plate it became, and where its answer will be
  defp plate(%{mount: mount, n: n}, base), do: %{queued: true, mount: mount, plate: n, answer_in: base <> ".solve.json"}
  defp plate(%{error: why}, _), do: %{queued: false, why: why}
  defp plate(_, _), do: nil

  # the calibration it was steering by; when it's off, the mount's last saved one, said to be so
  defp lock(%{state: state} = lock, saved) do
    lock
    |> Map.take([:state, :why, :target, :mount, :step, :rates, :error_px, :offset, :calibration])
    |> Map.put(:holding, state in [:holding, :coasting])
    |> then(&if(&1[:calibration] == nil and saved != nil, do: Map.put(&1, :saved_calibration, saved), else: &1))
  end

  defp lock(_, _), do: nil

  # JSON's kinds only: tuples become lists, atoms and times become strings, nothing that can't be
  # written (a pid, a function) gets in. What isn't known is left out, except the mount and the
  # pointing: those say null, so "there was none" can't be mistaken for "nobody wrote it down".
  defp plain(%DateTime{} = t), do: DateTime.to_iso8601(t)
  defp plain(%_{} = s), do: s |> Map.from_struct() |> plain()
  defp plain(m) when is_map(m), do: for({k, v} <- m, v != nil or k in [:pointing, :mount], into: %{}, do: {to_string(k), plain(v)})
  defp plain(l) when is_list(l), do: Enum.map(l, &plain/1)
  defp plain(t) when is_tuple(t), do: t |> Tuple.to_list() |> plain()
  defp plain(v) when is_boolean(v) or is_nil(v) or is_number(v) or is_binary(v), do: v
  defp plain(a) when is_atom(a), do: Atom.to_string(a)
  defp plain(other), do: inspect(other)
end
