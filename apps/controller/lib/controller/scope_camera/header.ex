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

  alias Controller.Sky.{Astro, Lineup, Pointing}
  alias Controller.Settings

  # IMX307: 2.9 µm pixels
  @pixel_um 2.9

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

  defp standard(record, ctx, began, ended, exp_s, stack, binned) do
    site = ctx[:site] || %{}
    pointing = ctx[:pointing]

    [
      {"ROWORDER", "TOP-DOWN", "first row is the top of the picture"},
      {"IMAGETYP", "LIGHT", "a picture of the sky"},
      {"DATE-OBS", began, "exposure start, UTC"},
      {"DATE-END", ended, "exposure end (frame arrived), UTC"},
      {"DATE", DateTime.utc_now(), "file written, UTC"},
      {"TIMESYS", "UTC"},
      {"EXPTIME", exp_s, "seconds, each frame"},
      {"EXPOSURE", exp_s, "seconds, each frame"},
      {"NCOMBINE", stack, "frames averaged into this one"},
      {"GAIN", record[:gain], "camera gain setting"},
      {"INSTRUME", ctx[:camera_name], "camera"},
      {"XPIXSZ", if(binned, do: @pixel_um * binned), "pixel size, um, binned"},
      {"YPIXSZ", if(binned, do: @pixel_um * binned), "pixel size, um, binned"},
      {"XBINNING", binned, "capture pixels per picture pixel, across"},
      {"YBINNING", binned, "capture pixels per picture pixel, down"},
      {"TELESCOP", if(ctx[:mount], do: "EQ6-R (#{ctx.mount.id})"), "mount"},
      {"FOCALLEN", Settings.get("focal_length_mm"), "mm"},
      {"APTDIA", Settings.get("aperture_mm"), "mm"},
      {"SITELAT", site[:lat], "degrees north"},
      {"SITELONG", site[:lon], "degrees east"},
      {"SWCREATE", "Observatory", "github.com/bradgessler/observatory"}
    ] ++ pointed(pointing, site, began)
  end

  # where the model says the scope pointed at the exposure's start
  defp pointed({ra, dec, source}, site, at) when is_number(ra) and is_number(dec) do
    altaz =
      if is_number(site[:lat]) and is_number(site[:lon]),
        do: Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(at, site.lon))

    [
      {"RA", Float.round(ra * 1.0, 5), "degrees, from the #{source}"},
      {"DEC", Float.round(dec * 1.0, 5), "degrees, from the #{source}"},
      {"OBJCTRA", hms(ra), "from the #{source}"},
      {"OBJCTDEC", dms(dec), "from the #{source}"},
      {"EQUINOX", 2000.0}
    ] ++
      case altaz do
        {alt, az} ->
          [{"CENTALT", Float.round(alt * 1.0, 3), "degrees"}, {"CENTAZ", Float.round(az * 1.0, 3), "degrees"}] ++
            if(alt > 1, do: [{"AIRMASS", Float.round(1 / :math.sin(alt * :math.pi() / 180), 4)}], else: [])

        _ ->
          []
      end ++ [{"OBS POINTING SOURCE", source}]
  end

  defp pointed(_, _, _), do: [{"OBS POINTING SOURCE", "none: not homed or lined up"}]

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
  model, where it pointed, the site, the box. Never raises: what can't be
  had is left out.
  """
  def context(mount_id, at) do
    site = safe(fn -> Pointing.site() end) || %{}

    %{
      site: Map.take(site, [:lat, :lon]),
      node: to_string(node()),
      firmware: firmware(),
      model: mount_id && safe(fn -> Lineup.status(mount_id) |> Map.take([:n, :rms_arcmin, :stale?, :axis_words]) end),
      pointing: mount_id && pointing(mount_id, at)
    }
  end

  @doc "A mount's snapshot, or nil."
  def snapshot(nil), do: nil
  def snapshot(id), do: safe(fn -> Mount.snapshot(id) end)

  defp pointing(id, at) do
    with %{} = snap <- snapshot(id),
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

  defp hms(ra) do
    h = ra / 15
    {hh, rest} = {trunc(h), (h - trunc(h)) * 60}
    {mm, ss} = {trunc(rest), (rest - trunc(rest)) * 60}
    "#{pad(hh)} #{pad(mm)} #{:erlang.float_to_binary(ss, decimals: 1) |> String.pad_leading(4, "0")}"
  end

  defp dms(dec) do
    sign = if dec < 0, do: "-", else: "+"
    d = abs(dec)
    {dd, rest} = {trunc(d), (d - trunc(d)) * 60}
    {mm, ss} = {trunc(rest), round((rest - trunc(rest)) * 60)}
    "#{sign}#{pad(dd)} #{pad(mm)} #{pad(min(ss, 59))}"
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end
end
