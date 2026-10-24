defmodule Controller.ScopeCamera.Header do
  @moduledoc """
  Everything known about a frame when it was taken, as FITS header cards
  (`Controller.Fits`): in the file, never drawn on the picture.

  **Standard keywords first**, the ones capture programs (N.I.N.A., MaxIm DL,
  SGP) write and stackers and solvers read: `DATE-OBS`, `DATE-END`,
  `EXPTIME`, `NCOMBINE`, `GAIN`, `IMAGETYP`, `INSTRUME`, `TELESCOP`,
  `XPIXSZ`/`XBINNING`, `FOCALLEN`/`APTDIA` when known, the site
  (`SITELAT`, `SITELONG`), and where the scope pointed when the model can
  say (`RA`/`DEC`, `OBJCTRA`/`OBJCTDEC`, `CENTALT`/`CENTAZ`, `AIRMASS`).

  **Ours on top**, `HIERARCH OBS …` (issue #92):

    * `OBS FRAME …` the frame's number on this box, why it was taken, how
      long the grab and the measuring took, and what the box measured
      (background, noise, brightest pixel, stars, half-flux radius, verdict)
    * `OBS CAMERA …` the camera: name, driver, USB id, serial, the mode it
      was read in, how the picture was made from it (luma, averaged 2 × 2),
      and every control it reported (`OBS CAMERA CTRL GAIN`, …)
    * `OBS MOUNT …` the mount at the start and the end of the grab: both
      axes' encoder degrees and steps, running or not, tracking
    * `OBS MODEL …` the alignment in force: points, rms, the polar axis
    * `OBS BOX …` which box, which firmware

  Times are UTC. The exposure's start is worked out from when the last
  frame arrived: the picture is the last `NCOMBINE` frames, each
  `EXPTIME` long, so it began that long before the grab ended.
  """

  alias Controller.Metadata.{Fits, Sensor}
  alias Controller.Sky.{Lineup, Pointing, Tracker}
  alias Controller.Settings

  @doc "Header cards for a frame, from its record (what was asked, what was found) and the moment's context."
  def cards(record, ctx) do
    exp_s = (record[:exposure_ms] || 0) / 1000
    stack = record[:stack] || 1
    ended = ctx[:ended_at] || record.at
    began = DateTime.add(ended, -round(exp_s * stack * 1000), :millisecond)
    {cw, _ch} = ctx[:capture_size] || {nil, nil}
    binned = cw && record[:w] && div(cw, record[:w])

    standard(record, ctx, began, ended, exp_s, stack, binned) ++
      frame(record) ++
      camera(ctx, binned) ++
      mount(ctx) ++
      model(ctx) ++
      box(ctx) ++
      [
        {:comment, "Kept by the Observatory frames pipeline. HIERARCH OBS keywords are the box's own:"},
        {:comment, "the frame, the camera and its controls, the mount at the grab's start and end, the model."},
        {:comment, "Times are UTC; DATE-OBS is worked out as DATE-END minus NCOMBINE x EXPTIME."}
      ]
  end

  # the standard cards, from the one keyword map every writer shares (`Controller.Metadata.Fits`)
  defp standard(record, ctx, began, ended, exp_s, stack, binned) do
    {ra, dec, source} = with({ra, dec, source} <- ctx[:pointing], do: {ra, dec, source}, else: (_ -> {nil, nil, nil}))
    profile = Sensor.profile(ctx[:camera_name]) || if(record[:sim] || ctx[:camera_name] == "Simulated camera", do: Sensor.profile("IMX307"))

    [{"ROWORDER", "TOP-DOWN", "first row is the top of the picture"}] ++
      Fits.cards(%{
        # a live view frame is a look, not a frame for a stack
        type: if(record[:why] == "live view", do: :snapshot, else: :light),
        began: began,
        ended: ended,
        written: DateTime.utc_now(),
        exposure_s: exp_s,
        ncombine: stack,
        gain: record[:gain],
        instrument: ctx[:camera_name],
        telescope: telescope(),
        observer: observer(),
        focal_length_mm: Settings.get("focal_length_mm"),
        aperture_mm: Settings.get("aperture_mm"),
        pixel_um: profile && profile.pixel_um,
        binning: binned,
        site: ctx[:site],
        object: ctx[:target],
        pointing: if(is_number(ra) and is_number(dec), do: %{ra_deg: ra, dec_deg: dec, source: source}),
        software: Fits.software_name(ctx[:firmware])
      }) ++
      [
        {"OBS POINTING SOURCE", source || "none: not homed or lined up"},
        {"OBS MOUNT NAME", if(ctx[:mount], do: "EQ6-R (#{ctx.mount.id})"), "the mount"}
      ]
  end

  @doc "The optical tube's name for `TELESCOP` (`Settings` `\"telescope\"`, else `config :controller, :telescope`), or nil."
  def telescope, do: name_setting("telescope")

  @doc "Who observed, for `OBSERVER` (`Settings` `\"observer\"`, else `config :controller, :observer`), or nil."
  def observer, do: name_setting("observer")

  defp name_setting(key) do
    case safe(fn -> Settings.get(key) end) do
      v when is_binary(v) and v != "" -> v
      _ -> Application.get_env(:controller, String.to_atom(key))
    end
  end

  defp frame(r) do
    [
      {"OBS FRAME SEQ", r[:seq], "frame number on this box, counting up"},
      {"OBS FRAME WHY", r[:why]},
      {"OBS FRAME TOOK MS", r[:took_ms], "grab and measure"},
      {"OBS FRAME GRAB MS", r[:grab_ms], "opening the camera and reading it"},
      {"OBS FRAME MEASURE MS", r[:measure_ms], "finding the stars on the box"},
      {"OBS FRAME VERDICT", r[:verdict]},
      {"OBS FRAME BACKGROUND", r[:background], "median, 0-255"},
      {"OBS FRAME NOISE", r[:noise], "from the median absolute deviation"},
      {"OBS FRAME MAX", r[:max], "brightest pixel"},
      {"OBS FRAME SATURATED PCT", r[:saturated_pct]},
      {"OBS FRAME STARS", r[:stars]},
      {"OBS FRAME HFR PX", r[:hfr_px], "half-flux radius, smaller is sharper"}
    ]
  end

  defp camera(ctx, binned) do
    info = ctx[:camera_info] || %{}
    {cw, ch} = ctx[:capture_size] || {nil, nil}

    [
      {"OBS CAMERA NAME", ctx[:camera_name]},
      {"OBS CAMERA DRIVER", info[:driver]},
      {"OBS CAMERA USB ID", info[:usb_id]},
      {"OBS CAMERA SERIAL", info[:serial]},
      {"OBS CAMERA BUS", info[:bus]},
      {"OBS CAMERA MODE", ctx[:mode_words]},
      {"OBS CAMERA FORMAT", ctx[:format], "pixel format read from the camera"},
      {"OBS CAMERA CAPTURE W", cw},
      {"OBS CAMERA CAPTURE H", ch},
      {"OBS CAMERA FPS", ctx[:fps], "frame rate asked for"},
      {"OBS CAMERA CHANNEL", "luma", "brightness only (Y), as the camera sends it"},
      {"OBS CAMERA SCALING", if(binned && binned > 1, do: "#{binned}x#{binned} average", else: "none"), "by ffmpeg, after the camera"}
    ] ++
      for {name, value} <- Enum.sort(ctx[:controls] || %{}), do: {"OBS CAMERA CTRL #{String.upcase(name)}", value}
  end

  defp mount(%{mount: %{id: id} = m}) do
    [{"OBS MOUNT ID", id}] ++ snap("START", m[:start]) ++ snap("END", m[:end])
  end

  defp mount(_), do: []

  defp snap(_when, nil), do: []

  defp snap(w, s) do
    [
      {"OBS MOUNT #{w} CONNECTED", s[:connected]},
      {"OBS MOUNT #{w} TRACKING", s[:tracking]},
      {"OBS MOUNT #{w} HOMED", s[:homed]}
    ] ++
      for axis <- [:ra, :dec], a = get_in(s, [:axes, axis]), a != nil, {k, v} <- axis_cards(a) do
        {"OBS MOUNT #{w} #{String.upcase(to_string(axis))} #{k}", v}
      end
  end

  defp axis_cards(a) do
    [
      {"DEG", round5(a[:degrees])},
      {"STEPS", a[:steps]},
      {"RUNNING", a[:running]},
      {"DEG PER S", a[:deg_per_s]}
    ]
  end

  defp round5(v) when is_number(v), do: Float.round(v * 1.0, 5)
  defp round5(_), do: nil

  defp model(%{model: %{} = st}) do
    [
      {"OBS MODEL POINTS", st[:n], "star alignment points in force"},
      {"OBS MODEL RMS ARCMIN", if(is_number(st[:rms_arcmin]), do: Float.round(st.rms_arcmin * 1.0, 2))},
      {"OBS MODEL STALE", st[:stale?]},
      # the polar axis in numbers (the altitude gives the latitude away: internal files only)
      {"OBS MODEL AXIS OFF DEG", round5(st[:axis_off_deg]), "polar axis from the pole"},
      {"OBS MODEL AXIS ALT DEG", round5(st[:axis_alt_deg]), "polar axis altitude"},
      {"OBS MODEL AXIS AZ DEG", round5(st[:axis_az_deg]), "polar axis azimuth"},
      {"OBS MODEL POLAR AXIS", st[:axis_words]}
    ]
  end

  defp model(_), do: []

  defp box(ctx) do
    [
      {"OBS BOX NODE", ctx[:node]},
      {"OBS BOX FIRMWARE", ctx[:firmware], "nerves_fw_uuid"}
    ]
  end

  # -- the moment's context, gathered when the frame is taken --------------------------------

  @doc """
  What the header needs from the moment a frame is taken that the frame
  itself doesn't know: the mount (`snapshot` at the start and end), the
  model, where it pointed, the site, the box, the hold's target. Never
  raises: what can't be had is left out. `snap` is the mount as it was at
  `at`, when the caller has it (a still's sample nearest the shutter): its
  pointing is worked out from that, not from where the mount is now.
  """
  def context(mount_id, at, snap \\ nil) do
    site = safe(fn -> Pointing.site() end) || %{}

    %{
      site: Map.take(site, [:lat, :lon, :elevation_m]),
      node: to_string(node()),
      firmware: firmware(),
      model: mount_id && safe(fn -> Lineup.status(mount_id) |> Map.take([:n, :rms_arcmin, :stale?, :axis_words, :axis_off_deg, :axis_alt_deg, :axis_az_deg]) end),
      pointing: mount_id && pointing(mount_id, at, snap),
      target: mount_id && target(mount_id)
    }
  end

  @doc """
  What the hold on mount `id` is on: the catalogue object (`%{id, name, ra_deg, dec_deg}`) and,
  as `aim`, where the hold actually points when centring or a dither has moved it off the
  catalogue place. nil with no hold.
  """
  def target(id) do
    case safe(fn -> Tracker.status(id) end) do
      %{} = st ->
        t = st[:target] || %{}
        aim = st[:aim] || %{}
        name = t[:name] || st[:name]

        if name do
          %{id: t[:id], name: name, ra_deg: t[:ra_deg] || aim[:ra_deg], dec_deg: t[:dec_deg] || aim[:dec_deg]}
          |> then(fn o -> if is_number(aim[:ra_deg]) and is_number(aim[:dec_deg]), do: Map.put(o, :aim, %{ra_deg: aim.ra_deg, dec_deg: aim.dec_deg}), else: o end)
        end

      _ ->
        nil
    end
  end

  @doc "A mount's snapshot, or nil."
  def snapshot(nil), do: nil
  def snapshot(id), do: safe(fn -> Mount.snapshot(id) end)

  defp pointing(id, at, snap) do
    with %{} = snap <- if(is_map(snap) and is_map(snap[:axes]), do: snap, else: snapshot(id)),
         %{} = ctx <- safe(fn -> Pointing.context(at, id) end),
         {ra, dec} <- safe(fn -> Pointing.scope_radec(Map.put(snap, :homed, snap[:homed] == true), ctx) end) do
      {ra, dec, if(is_map(ctx[:model]), do: "star alignment", else: "home position")}
    else
      _ -> nil
    end
  end

  defp firmware do
    if Code.ensure_loaded?(Nerves.Runtime.KV), do: safe(fn -> apply(Nerves.Runtime.KV, :get_active, ["nerves_fw_uuid"]) end)
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end
end
