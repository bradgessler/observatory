defmodule Controller.Metadata.Fits do
  @moduledoc """
  The one keyword map: what the box knows about a frame, as FITS header
  cards with the names every astronomy program reads (`docs/metadata.md`,
  Stage 1). The stills' sidecar carries these cards as its `fits` block and
  the telescope camera writes them into its FITS files
  (`Controller.ScopeCamera.Header`), so the two can never name a thing two
  ways.

  Order of preference, as the spec has it: FITS 4.0 and its registered
  conventions (WCS), then what capture programs write (N.I.N.A., MaxIm DL),
  then ours under `HIERARCH OBS ...` for what has no standard. A standard
  keyword is only ever used for what it means: `OBJCTRA`/`OBJCTDEC` are the
  target's catalogue place, `RA`/`DEC` where the mount pointed, `TELESCOP`
  the optical tube (the mount is `OBS MOUNT NAME`).

      Fits.cards(%{type: :light, began: t0, exposure_s: 15.0, object: %{name: "M27", id: "m27", ...}})
      #=> [{"IMAGETYP", "LIGHT", "..."}, {"DATE-OBS", ~U[...], "..."}, ..., {"OBJECT", "M 27", ...}]

  What goes in (`facts`), each optional; what is not known is left out:

    * `type:` `:light`, `:dark`, `:flat`, `:bias` or `:snapshot` (a frame
      not meant for a stack: focus, centring, live view) -> `IMAGETYP`
    * `began:`, `ended:` (DateTime, UTC), `exposure_s:`, `ncombine:`,
      `written:` -> `DATE-OBS`/`DATE-BEG`/`DATE-END`/`DATE-AVG`, the same as
      `MJD-*`, `TIMESYS`, `EXPTIME`, `EXPOSURE`, `XPOSURE`, `NCOMBINE`, `DATE`
    * `object:` `%{name, id, ra_deg, dec_deg}` (the target, from the hold) ->
      `OBJECT` (SIMBAD's form: `M 27`, `NGC 6853`), `OBJCTRA`, `OBJCTDEC`,
      `OBJCTHA` with a site
    * `pointing:` `%{ra_deg, dec_deg, source}` (where the model says the
      scope pointed) -> `RA`, `DEC`, `CENTALT`, `CENTAZ`, `AIRMASS` with a
      site; `RADESYS = 'ICRS'` and `EQUINOX = 2000.0` with any celestial place
    * `site:` `%{lat, lon, elevation_m}` -> `SITELAT`, `SITELONG`,
      `SITEELEV` and `OBSGEO-B/L/H`
    * `instrument:`, `telescope:`, `observer:` -> `INSTRUME`, `TELESCOP`,
      `OBSERVER`
    * `focal_length_mm:`, `aperture_mm:` -> `FOCALLEN`, `APTDIA`, `FOCRATIO`
    * `pixel_um:`, `binning:`, `cfa:` -> `XPIXSZ`, `YPIXSZ`, `XBINNING`,
      `YBINNING`, `BAYERPAT`, `XBAYROFF`, `YBAYROFF`
    * `iso:`, `gain:` -> `ISOSPEED`, `GAIN`
    * `rotation_deg:` (from a solve) -> `ROTATANG`
    * `software:` -> `SWCREATE` (`software/1` makes it)
    * `ours:` `[{"OBS ...", value, comment}]`, appended as they are

  Locations and altitudes are internal only (see Privacy in the spec): the
  cards go into the box's own files, never into anything published.
  """

  alias Controller.Sky.Astro

  @doc "Ordered cards (`{key, value, comment}`, as `Controller.Fits` takes them) for a frame's facts."
  def cards(facts) do
    (kind(facts) ++ time(facts) ++ instrument(facts) ++ site(facts) ++ target(facts) ++ pointing(facts) ++ software(facts))
    |> Kernel.++(facts[:ours] || [])
    |> Enum.reject(fn c -> not free?(c) and elem(c, 1) == nil end)
    # each keyword once (the target and the pointing both bring RADESYS): the first one stands
    |> Enum.uniq_by(fn c -> if free?(c), do: make_ref(), else: elem(c, 0) end)
  end

  defp free?(c), do: elem(c, 0) in [:comment, :history]

  @doc """
  The cards as a JSON object, keyword to value, in the cards' order (`Jason.OrderedObject`): the
  sidecar's `fits` block. Times are written as FITS writes them (`2026-10-18T03:21:39.655`, UTC);
  our own keywords keep their `OBS ...` name (FITS writes them `HIERARCH OBS ...`, and that is how
  astropy names them too). Comments are left out: the JSON beside it says what each one is.
  """
  def json(cards) do
    cards
    |> Enum.reject(&(elem(&1, 0) in [:comment, :history]))
    |> Enum.map(fn c -> {elem(c, 0), json_value(elem(c, 1))} end)
    |> Enum.uniq_by(&elem(&1, 0))
    |> Jason.OrderedObject.new()
  end

  defp json_value(%DateTime{} = t), do: stamp(t)
  defp json_value(v) when is_atom(v) and not is_boolean(v), do: Atom.to_string(v)
  defp json_value(v), do: v

  # -- the standard cards -------------------------------------------------------------------------

  defp kind(f) do
    case imagetyp(f[:type]) do
      nil -> []
      t -> [{"IMAGETYP", t, "frame type"}]
    end
  end

  @doc "`IMAGETYP` for a frame type, in N.I.N.A.'s upper case (Siril and PixInsight read it either way)."
  def imagetyp(t) when t in [:light, "light"], do: "LIGHT"
  def imagetyp(t) when t in [:dark, "dark"], do: "DARK"
  def imagetyp(t) when t in [:flat, "flat"], do: "FLAT"
  def imagetyp(t) when t in [:bias, "bias"], do: "BIAS"
  def imagetyp(t) when t in [:snapshot, "snapshot"], do: "SNAPSHOT"
  def imagetyp(_), do: nil

  defp time(f) do
    began = f[:began]
    exp = num(f[:exposure_s])
    ended = f[:ended] || (began && exp && DateTime.add(began, round(exp * 1000), :millisecond))
    mid = began && ended && DateTime.add(began, div(DateTime.diff(ended, began, :millisecond), 2), :millisecond)

    [
      {"DATE-OBS", began, "exposure start, UTC"},
      {"DATE-BEG", began, "exposure start, UTC"},
      {"DATE-AVG", mid, "middle of the exposure, UTC"},
      {"DATE-END", ended, "exposure end, UTC"},
      {"MJD-OBS", began && mjd(began), "exposure start, MJD (UTC)"},
      {"MJD-AVG", mid && mjd(mid), "middle of the exposure, MJD (UTC)"},
      {"MJD-END", ended && mjd(ended), "exposure end, MJD (UTC)"},
      {"TIMESYS", if(began, do: "UTC"), "times are UTC"},
      {"DATE", f[:written], "file written, UTC"},
      {"EXPTIME", exp, "seconds"},
      {"EXPOSURE", exp, "seconds"},
      {"XPOSURE", exp && exp * (f[:ncombine] || 1), "seconds of light in the frame"},
      {"NCOMBINE", f[:ncombine], "frames averaged into this one"}
    ]
  end

  defp instrument(f) do
    focal = num(f[:focal_length_mm])
    aperture = num(f[:aperture_mm])
    bin = f[:binning]
    pixel = num(f[:pixel_um])
    pixel = pixel && Float.round(pixel * (bin || 1), 3)

    [
      {"INSTRUME", f[:instrument], "camera"},
      {"TELESCOP", f[:telescope], "optical tube"},
      {"OBSERVER", f[:observer]},
      {"FOCALLEN", focal, "mm"},
      {"APTDIA", aperture, "mm"},
      {"FOCRATIO", if(focal && aperture && aperture > 0, do: Float.round(focal / aperture, 2)), "focal length over aperture"},
      {"XPIXSZ", pixel, "pixel size, um" <> if(bin && bin > 1, do: ", binned", else: "")},
      {"YPIXSZ", pixel, "pixel size, um" <> if(bin && bin > 1, do: ", binned", else: "")},
      {"XBINNING", bin, "sensor pixels per frame pixel, across"},
      {"YBINNING", bin, "sensor pixels per frame pixel, down"},
      {"BAYERPAT", f[:cfa], "colour filter array, top-left first"},
      {"XBAYROFF", f[:cfa] && 0},
      {"YBAYROFF", f[:cfa] && 0},
      {"ISOSPEED", if(is_integer(f[:iso]), do: f[:iso]), "ISO"},
      {"GAIN", f[:gain], "camera gain setting"}
    ]
  end

  defp site(f) do
    site = f[:site] || %{}
    {lat, lon, h} = {num(site[:lat]), num(site[:lon]), num(site[:elevation_m])}

    [
      {"SITELAT", lat, "degrees north"},
      {"SITELONG", lon, "degrees east"},
      {"SITEELEV", h, "metres"},
      {"OBSGEO-B", lat, "degrees north"},
      {"OBSGEO-L", lon, "degrees east"},
      {"OBSGEO-H", h, "metres"}
    ]
  end

  defp target(%{object: %{} = o} = f) do
    {ra, dec} = {num(o[:ra_deg]), num(o[:dec_deg])}
    site = f[:site] || %{}

    ha =
      if ra && f[:began] && is_number(site[:lon]),
        do: Float.round(Astro.hour_angle(Astro.lst_deg(f.began, site.lon), ra) / 15, 4)

    [
      {"OBJECT", simbad_name(o[:id], o[:name]), "target"},
      {"OBJCTRA", ra && hms(ra), "target, catalogue (ICRS), HH MM SS.s"},
      {"OBJCTDEC", dec && dms(dec), "target, catalogue (ICRS), +DD MM SS"},
      {"OBJCTHA", ha, "target's hour angle at the start, hours"}
    ] ++ frame_of(ra && dec)
  end

  defp target(_), do: []

  defp pointing(%{pointing: %{ra_deg: ra, dec_deg: dec} = p} = f) when is_number(ra) and is_number(dec) do
    site = f[:site] || %{}
    from = if p[:source], do: "from the #{p.source}", else: "where the mount pointed"

    altaz =
      if f[:began] && is_number(site[:lat]) && is_number(site[:lon]),
        do: Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(f.began, site.lon))

    [
      {"RA", Float.round(ra * 1.0, 5), "degrees, where the mount pointed, #{from}"},
      {"DEC", Float.round(dec * 1.0, 5), "degrees, where the mount pointed, #{from}"}
    ] ++
      case altaz do
        {alt, az} ->
          [{"CENTALT", Float.round(alt * 1.0, 3), "degrees"}, {"CENTAZ", Float.round(az * 1.0, 3), "degrees"}, {"AIRMASS", airmass(alt), "Kasten and Young"}]

        _ ->
          []
      end ++ frame_of(true) ++ [{"ROTATANG", num(f[:rotation_deg]), "degrees, from a plate solve"}]
  end

  defp pointing(f), do: [{"ROTATANG", num(f[:rotation_deg]), "degrees, from a plate solve"}]

  defp frame_of(true), do: [{"RADESYS", "ICRS", "celestial frame"}, {"EQUINOX", 2000.0}]
  defp frame_of(_), do: []

  defp software(f), do: [{"SWCREATE", f[:software], "github.com/bradgessler/observatory"}]

  # -- helpers, public so the other writers say things the same way --------------------------------

  @doc "Modified Julian Date (JD - 2400000.5) of a UTC time, to the millisecond."
  def mjd(%DateTime{} = t), do: Float.round(Astro.julian_date(t) - 2_400_000.5, 8)

  @doc "A UTC time as FITS writes it: ISO 8601 to the millisecond, no zone (`TIMESYS` says UTC)."
  def stamp(%DateTime{} = t), do: t |> DateTime.truncate(:millisecond) |> DateTime.to_naive() |> NaiveDateTime.to_iso8601()

  @doc """
  Airmass at an apparent altitude in degrees (Kasten and Young 1989), which stays finite near the
  horizon where `1/sin(alt)` does not; nil below it.
  """
  def airmass(alt) when is_number(alt) and alt > 0 do
    Float.round(1 / (:math.sin(alt * :math.pi() / 180) + 0.50572 * :math.pow(alt + 6.07995, -1.6364)), 4)
  end

  def airmass(_), do: nil

  @doc """
  A target's name as SIMBAD resolves it, from the catalogue's id: `m27` is `M 27`, `ngc6853` is
  `NGC 6853`, `hip32349` is `HIP 32349`. Anything else (a planet, a name typed with a place) is
  its name as given.
  """
  def simbad_name(id, name) do
    case Regex.run(~r/\A(m|ngc|ic|hip|hd|sh2-|c|mel|cr)\s*(\d+[a-z]?)\z/i, to_string(id || "")) do
      [_, cat, n] -> "#{catalogue(String.downcase(cat))} #{String.upcase(n)}"
      _ -> name && to_string(name)
    end
  end

  defp catalogue("m"), do: "M"
  defp catalogue("ngc"), do: "NGC"
  defp catalogue("ic"), do: "IC"
  defp catalogue("hip"), do: "HIP"
  defp catalogue("hd"), do: "HD"
  defp catalogue("sh2-"), do: "Sh2-"
  defp catalogue("c"), do: "C"
  defp catalogue("mel"), do: "Mel"
  defp catalogue("cr"), do: "Cr"

  @doc "`INSTRUME` for a camera: `Sony ILCE-6000` from its maker's long name and its model."
  def instrument_name(manufacturer, model) do
    maker = manufacturer && manufacturer |> to_string() |> String.replace(~r/\s+(Corporation|Corp\.?|Inc\.?|Co\.,? Ltd\.?|Ltd\.?)\z/i, "")

    case {maker, model} do
      {nil, nil} -> nil
      {nil, m} -> to_string(m)
      {mk, nil} -> mk
      {mk, m} -> if String.starts_with?(to_string(m), mk), do: to_string(m), else: "#{mk} #{m}"
    end
  end

  @doc """
  `SWCREATE`: this software and its version, and the firmware it runs in when it runs on a box
  (`nerves_fw_uuid`, which names the build exactly).
  """
  def software_name(firmware \\ nil) do
    vsn = Application.spec(:controller, :vsn)
    base = "Observatory" <> if(vsn, do: " #{vsn}", else: "")
    if is_binary(firmware) and firmware != "", do: base <> " (firmware #{String.slice(firmware, 0, 8)})", else: base
  end

  @doc "Right ascension in degrees as `HH MM SS.s`."
  def hms(ra) do
    total = round(Astro.norm360(ra * 1.0) / 15 * 36_000)
    total = rem(total, 24 * 36_000)
    {hh, rest} = {div(total, 36_000), rem(total, 36_000)}
    {mm, tenths} = {div(rest, 600), rem(rest, 600)}
    "#{pad(hh)} #{pad(mm)} #{pad(div(tenths, 10))}.#{rem(tenths, 10)}"
  end

  @doc "Declination in degrees as `+DD MM SS`."
  def dms(dec) do
    sign = if dec < 0, do: "-", else: "+"
    total = round(abs(dec) * 3600)
    {dd, rest} = {div(total, 3600), rem(total, 3600)}
    "#{sign}#{pad(dd)} #{pad(div(rest, 60))} #{pad(rem(rest, 60))}"
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp num(v) when is_integer(v), do: v * 1.0
  defp num(v) when is_float(v), do: v
  defp num(_), do: nil
end
