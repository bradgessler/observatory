defmodule Controller.StillCamera.Sidecar do
  @moduledoc """
  Everything known about a stills picture when it was taken, kept in a JSON
  file beside it (`20261003-162024-DSC00001.json` next to the `.ARW` and the
  `.JPG`). The camera's own files are never opened for writing: no tag goes
  into the RAW or the JPEG, and each file's SHA-256 is in the sidecar so that
  can be checked later. One line per picture is also added to the night's
  `index.jsonl`, the same record, so a night can be read without opening
  every file.

  What is in it (`"schema": "observatory.still/2"`; every field of
  `observatory.still/1` is still there with the same meaning, so its readers
  read this too):

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
      of the centre, field, rotation, the whole WCS; or why it wasn't solved).

  New in `/2` (`docs/metadata.md`):

    * `capture`: what the picture was taken for. `purpose` (`light`, `dark`,
      `flat`, `focus`, `centring`, `finder`, `test`), the hold's `target`
      as the shutter was pressed (`%{name, id, ra_deg, dec_deg}`: the
      catalogue's place, and `aim` when centring or a dither has moved the
      hold off it), `run` (`%{id, k}`: which run of pictures, and this one's
      number in it, counted from 1) and `plan` (`%{run, step, index, of}`,
      when an observing plan ran the camera). What a stack groups frames by.
    * `fits`: the same facts as FITS keywords, keyword to value, in order:
      standard ones first, ours as `OBS ...` (`Controller.Metadata.Fits`,
      the map the telescope camera's FITS files use too).
    * `camera.serial`, `camera.firmware`, `camera.program`, and the camera's
      own clock: `clock_reads` (its capture date, as it says it),
      `clock_offset_s` (that less the shutter press) and `clock_set` (whether
      the box set its clock this connection, `Camera.Sony.set_clock/4`).
    * `sensor`: the camera's sensor by model (`Controller.Metadata.Sensor`).
    * `model.axis_off_deg`, `axis_alt_deg`, `axis_az_deg`: the polar axis in
      numbers beside `axis_words`; `time.clock_source` in one word.
    * Unknown is absent: `camera.f_number` is left out with no lens on the
      camera (it said 0.0), `tracking.smear_arcsec` without an exposure.

  It is as good as what was known that night: a mount that isn't homed has no
  RA/Dec, and the encoder positions are still there to work it out later.
  """

  alias Controller.Metadata.{Fits, Sensor}
  alias Controller.ScopeCamera.Header
  alias Controller.Sky.Astro
  alias Controller.Settings
  alias Controller.StillCamera.Optics

  @schema "observatory.still/2"
  @purposes ~w(light dark flat focus centring finder test)
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
  `measured`; and for `capture`: `purpose`, `target` (the hold's, read as the
  shutter was pressed; looked up now when not given), `run`, `plan`, and
  `camera_clock` (the camera's capture date for the picture). Anything
  missing is left out.
  """
  def build(shot) do
    camera = shot[:camera] || %{}
    # the settings the picture was taken at; without those, the camera's as it says now, and said to be so
    {settings, settings_from} = if is_map(shot[:settings]), do: {shot[:settings], "shutter"}, else: {camera[:settings] || %{}, camera[:settings] && "status"}
    exposure_s = seconds(settings[:shutter])
    pressed = shot[:pressed_at] || shot[:saved_at]
    ended = if exposure_s, do: DateTime.add(pressed, round(exposure_s * 1000), :millisecond), else: pressed
    # where the mount pointed is worked out from the mount as it was when the shutter opened, not as it is now
    ctx = Header.context(shot[:mount_id], pressed, snapshot_at(shot[:samples] || [], pressed))
    target = if Map.has_key?(shot, :target), do: shot[:target], else: ctx[:target]
    capture = capture(shot, target)
    camera_block = camera(camera, settings, settings_from, exposure_s, shot[:camera_clock], pressed)
    pointing = pointing(ctx[:pointing], ctx[:site], pressed)

    record =
      plain(%{
        schema: @schema,
        seq: shot[:seq],
        # what kind of frame: "light" (the sky) or a calibration frame taken on purpose: "dark" (the cap
        # on, the light's own exposure and ISO) or "flat" (an evenly lit sky). The stacking tools find
        # calibration frames by this (`stack-pictures/tools/darks.py`). Said for every picture since /2
        frame: %{type: to_string(shot[:frame] || :light)},
        # what it was taken for, the hold's target, the run and the plan it belongs to
        capture: capture,
        # where in the run's dither the picture was taken: `%{k, east_arcmin, north_arcmin, radius_arcmin}`
        # from the run's middle (`Controller.Sky.Dither`); nil when the run held still
        dither: shot[:dither],
        # how the mount's polar axis turns the field (`Controller.Sky.FieldRotation`): axis_off_deg, rate_deg_per_h,
        # corner_arcsec, smear_arcsec (predicted for this exposure), max_exposure_s and the tolerance it was worked to.
        # Facts only: a reader decides whether the smear matters
        tracking: tracking(shot[:tracking]),
        time: %{
          shutter_pressed: pressed,
          exposure_end: ended,
          exposure_s: exposure_s,
          picture_ready: shot[:ready_at],
          saved: shot[:saved_at],
          # a box that has just booted keeps its own time until the network sets it: times written then can be off by a minute
          clock:
            cond do
              Controller.Clock.synced?() -> "set by the network"
              Controller.Clock.set?() -> "set from a phone or another machine of the cluster"
              true -> "the box's own, not yet set by the network"
            end,
          # the same in one word: network, peer, phone or own (`Controller.Clock.source/0`)
          clock_source: safe(fn -> Controller.Clock.source() end),
          note: "UTC by the box's clock. shutter_pressed is when the box sent the press; the camera opens within tens of ms."
        },
        files: shot[:files],
        camera: camera_block,
        sensor: Sensor.profile(camera[:model]),
        optics: optics(),
        mount: mount(shot[:mount_id], shot[:samples] || [], pressed, ended),
        settling: shot[:settle] && shot.settle[:settling],
        settle: shot[:settle] && Map.take(shot.settle, [:since_slew_s, :settle_s]),
        cloud: shot[:sky] && shot.sky[:cloud],
        transparency: shot[:sky] && shot.sky[:transparency],
        transparency_from: if(is_map(shot[:sky]) and shot.sky[:cloud] != nil, do: Map.take(shot.sky, [:stars, :sky_ratio, :first])),
        pointing: pointing,
        model: ctx[:model],
        site: ctx[:site],
        lock_on: lock(shot[:lock], shot[:calibration]),
        measured: shot[:measured],
        plate_solve: plate(shot[:plate], Path.basename(to_string(shot[:files] |> List.first() |> Map.get(:name))) |> Path.rootname()),
        box: %{node: ctx[:node], firmware: ctx[:firmware]}
      })

    Map.put(record, "fits", fits(record, ctx, capture, camera_block, pointing, settings, pressed, ended, exposure_s, shot))
  end

  # the camera as it was for this picture: as the shutter was pressed where the driver read it then,
  # what it reports about itself, and its own clock against the box's
  defp camera(camera, settings, settings_from, exposure_s, camera_clock, pressed) do
    reads = camera_clock && Camera.Sony.parse_clock(camera_clock)

    %{
      id: camera[:id],
      model: camera[:model],
      manufacturer: camera[:manufacturer],
      serial: camera[:serial],
      firmware: camera[:firmware],
      iso: settings[:iso],
      shutter: settings[:shutter],
      exposure_s: exposure_s,
      quality: settings[:quality],
      # a camera with no lens on it says 0.0: that is no f-number, so it is left out
      f_number: if(is_number(settings[:f_number]) and settings[:f_number] > 0, do: settings[:f_number]),
      focus: settings[:focus],
      program: settings[:program],
      battery_pct: settings[:battery],
      settings_from: settings_from,
      # the camera's own clock: what it stamped this picture with, and how far that is from the box's press
      clock_reads: if(is_binary(camera_clock) and camera_clock != "", do: camera_clock),
      clock_offset_s: reads && pressed && DateTime.diff(reads, DateTime.truncate(pressed, :second), :second),
      clock_set: camera[:clock]
    }
  end

  # what the picture was taken for and of: `purpose`, the hold's `target`, the `run` and the `plan`
  defp capture(shot, target) do
    %{
      purpose: purpose(shot[:purpose], shot[:frame]),
      target: target,
      run: shot[:run],
      plan: shot[:plan]
    }
  end

  @doc """
  What a picture was taken for, in the sidecar's words: the one asked for (`purpose:`), else a
  calibration frame's type, else `"light"` (a picture of the sky for a stack).
  """
  def purpose(asked, frame \\ nil)
  def purpose(asked, _frame) when is_atom(asked) and not is_nil(asked), do: purpose(Atom.to_string(asked))
  def purpose(asked, _frame) when is_binary(asked), do: if(asked == "centre", do: "centring", else: asked)
  def purpose(nil, frame) when frame in [:dark, :flat, "dark", "flat"], do: to_string(frame)
  def purpose(_, _), do: "light"

  @doc "The purposes a picture can have."
  def purposes, do: @purposes

  # a smear worked out without an exposure is no smear: left out, never `false`
  defp tracking(%{} = t), do: if(is_number(t[:smear_arcsec]), do: t, else: Map.delete(t, :smear_arcsec))
  defp tracking(_), do: nil

  # the sample nearest the shutter's press, as the mount reported it
  defp snapshot_at([], _), do: nil

  defp snapshot_at(samples, at) do
    case Enum.filter(samples, fn {_, snap} -> is_map(snap) end) do
      [] -> nil
      found -> found |> Enum.min_by(fn {t, _} -> abs(DateTime.diff(t, at, :millisecond)) end) |> elem(1)
    end
  end

  # -- the FITS keywords (`Controller.Metadata.Fits`): the same facts, by their standard names ---

  defp fits(record, ctx, capture, camera, pointing, settings, pressed, ended, exposure_s, shot) do
    optics = record["optics"] || %{}
    sensor = Sensor.profile(camera[:model])
    purpose = capture.purpose

    facts = %{
      type: imagetyp(purpose),
      began: pressed,
      ended: ended,
      exposure_s: exposure_s,
      object: capture.target,
      pointing: pointing && %{ra_deg: pointing.ra_deg, dec_deg: pointing.dec_deg, source: pointing.source},
      site: ctx[:site],
      instrument: Fits.instrument_name(camera[:manufacturer], camera[:model]),
      telescope: Header.telescope(),
      observer: Header.observer(),
      focal_length_mm: optics["focal_length_mm"],
      aperture_mm: optics["aperture_mm"],
      pixel_um: sensor && sensor.pixel_um,
      binning: sensor && 1,
      cfa: sensor && sensor[:cfa],
      iso: settings[:iso],
      software: Fits.software_name(ctx[:firmware]),
      ours: ours(record, ctx, capture, camera, shot)
    }

    facts |> Fits.cards() |> Fits.json()
  end

  # IMAGETYP: what is meant for a stack is LIGHT, DARK or FLAT; anything else is a look (N.I.N.A.'s SNAPSHOT)
  defp imagetyp(p) when p in ["light", "dark", "flat"], do: String.to_atom(p)
  defp imagetyp(_), do: :snapshot

  defp ours(record, ctx, capture, camera, shot) do
    time = record["time"] || %{}
    model = ctx[:model] || %{}
    tracking = record["tracking"] || %{}
    dither = record["dither"] || %{}
    stars = get_in(record, ["measured", "star_size"]) || %{}
    run = capture.run || %{}
    plan = capture.plan || %{}

    [
      {"OBS SCHEMA", @schema},
      {"OBS FRAME SEQ", record["seq"], "picture number on this box"},
      {"OBS FRAME WHY", capture.purpose, "what it was taken for"},
      {"OBS RUN ID", run[:id], "the run of pictures it belongs to"},
      {"OBS RUN K", run[:k], "its number in the run, from 1"},
      {"OBS PLAN RUN", plan[:run], "the observing plan"},
      {"OBS PLAN STEP", plan[:step], "the plan's step"},
      {"OBS PLAN INDEX", plan[:index], "its number in the step, from 1"},
      {"OBS PLAN OF", plan[:of], "pictures the step asked for"},
      {"OBS TIME READY", shot[:ready_at], "the camera had the picture, UTC"},
      {"OBS TIME SAVED", shot[:saved_at], "saved on the box, UTC"},
      {"OBS CLOCK SOURCE", time["clock_source"], "where the box's time came from"},
      {"OBS CAMERA ID", camera[:id]},
      {"OBS CAMERA SERIAL", camera[:serial]},
      {"OBS CAMERA FIRMWARE", camera[:firmware]},
      {"OBS CAMERA SHUTTER", camera[:shutter], "as the camera words it"},
      {"OBS CAMERA QUALITY", camera[:quality]},
      {"OBS CAMERA FOCUS MODE", camera[:focus] && to_string(camera[:focus])},
      {"OBS CAMERA PROGRAM", camera[:program]},
      {"OBS CAMERA BATTERY PCT", camera[:battery_pct]},
      {"OBS CAMERA CLOCK", camera[:clock_reads], "the camera's own clock, as it stamped the picture"},
      {"OBS CAMERA CLOCK OFFSET S", camera[:clock_offset_s], "camera's clock less the box's"},
      {"OBS OPTICS FOCAL FROM", get_in(record, ["optics", "focal_length_from"])},
      {"OBS OPTICS FOCAL LABEL MM", get_in(record, ["optics", "focal_length_label_mm"])},
      {"OBS MOUNT ID", get_in(record, ["mount", "id"])},
      {"OBS MOUNT START TRACKING", get_in(record, ["mount", "start", "tracking"])},
      {"OBS MOUNT START HOMED", get_in(record, ["mount", "start", "homed"])},
      {"OBS MOUNT START RA DEG", get_in(record, ["mount", "start", "ra", "deg"])},
      {"OBS MOUNT START DEC DEG", get_in(record, ["mount", "start", "dec", "deg"])},
      {"OBS MOUNT START RA STEPS", get_in(record, ["mount", "start", "ra", "steps"])},
      {"OBS MOUNT START DEC STEPS", get_in(record, ["mount", "start", "dec", "steps"])},
      {"OBS MOUNT END RA DEG", get_in(record, ["mount", "end", "ra", "deg"])},
      {"OBS MOUNT END DEC DEG", get_in(record, ["mount", "end", "dec", "deg"])},
      {"OBS POINTING SOURCE", get_in(record, ["pointing", "source"])},
      {"OBS MODEL POINTS", model[:n], "star alignment points in force"},
      {"OBS MODEL RMS ARCMIN", model[:rms_arcmin]},
      {"OBS MODEL STALE", model[:stale?]},
      {"OBS MODEL AXIS OFF DEG", model[:axis_off_deg], "polar axis from the pole"},
      {"OBS MODEL AXIS ALT DEG", model[:axis_alt_deg], "polar axis altitude"},
      {"OBS MODEL AXIS AZ DEG", model[:axis_az_deg], "polar axis azimuth"},
      {"OBS TRACKING AXIS OFF DEG", tracking["axis_off_deg"]},
      {"OBS TRACKING ROT DEG PER H", tracking["rate_deg_per_h"], "the field's turn"},
      {"OBS TRACKING CORNER ARCSEC", tracking["corner_arcsec"]},
      {"OBS TRACKING SMEAR ARCSEC", tracking["smear_arcsec"], "the corners' smear in this exposure"},
      {"OBS TRACKING MAX EXP S", tracking["max_exposure_s"]},
      {"OBS TRACKING TOL ARCSEC", tracking["tolerance_arcsec"]},
      {"OBS SETTLING", record["settling"], "taken while the mount settled after a slew"},
      {"OBS SINCE SLEW S", get_in(record, ["settle", "since_slew_s"])},
      {"OBS SETTLE S", get_in(record, ["settle", "settle_s"])},
      {"OBS DITHER K", dither["k"]},
      {"OBS DITHER EAST ARCMIN", dither["east_arcmin"]},
      {"OBS DITHER NORTH ARCMIN", dither["north_arcmin"]},
      {"OBS DITHER RADIUS ARCMIN", dither["radius_arcmin"]},
      {"OBS LOCKON STATE", get_in(record, ["lock_on", "state"])},
      {"OBS LOCKON HOLDING", get_in(record, ["lock_on", "holding"])},
      {"OBS SKY CLOUD", record["cloud"]},
      {"OBS SKY TRANSPARENCY", record["transparency"], "stars' light against the clearest picture of the field"},
      {"OBS SKY TRANSP STARS", get_in(record, ["transparency_from", "stars"])},
      {"OBS FRAME BACKGROUND", get_in(record, ["measured", "background"]), "median, 0-255, of the grey copy"},
      {"OBS FRAME MAX", get_in(record, ["measured", "max"])},
      {"OBS FRAME STARS", get_in(record, ["measured", "stars"])},
      {"OBS STARS HFD ARCSEC", stars["arcsec"], "median half-flux diameter"},
      {"OBS STARS HFD PX", stars["px"]},
      {"OBS STARS HFD N", stars["n"]},
      {"OBS PLATE N", get_in(record, ["plate_solve", "plate"])},
      {"OBS PLATE ANSWER", get_in(record, ["plate_solve", "answer_in"])},
      {"OBS BOX NODE", ctx[:node]},
      {"OBS BOX FIRMWARE", ctx[:firmware], "nerves_fw_uuid"}
    ]
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
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
