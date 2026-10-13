defmodule Controller.Sky.Exposure do
  @moduledoc """
  A starting exposure for a target: ISO, shutter speed, and for the faint
  ones how many frames to stack (#117). Advice, not a setting: nothing here
  touches the camera, and the page that shows it keeps its own dials.

      Exposure.advise(saturn, aperture_mm: 203.2, focal_length_mm: 2032)
      #=> %{iso: 800, shutter: "1/60", shutter_s: 0.0167, range: {"1/60", "1/15"},
      #     confidence: :known, why: "From the surface brightness of Saturn, 6.8 mag per square arcsecond, at f/10.", ...}

  Three rules, by what the thing is:

    * **The Moon and the planets** are sunlit discs, so the exposure follows
      from surface brightness, f-ratio and ISO, the way a daylight exposure
      does: `seconds = N² / (ISO × B)`. `B` is 121 for a full Moon (Looney 11:
      f/11 at 1/ISO), less for a thinner phase, and for a planet 121 scaled by
      how much fainter or brighter its disc is per square arcsecond than the
      full Moon's (`@surface`). A disc's surface brightness does not change
      with its distance from us, so one number per planet holds all year.
    * **A star** is a point the air smears into a disc `star_arcsec:` wide.
      Its light over that disc is a surface brightness too, so the same
      equation gives the shutter that keeps its middle from clipping: a
      round star with its colour, not a deep exposure. Rough, because the
      star's size is the night's seeing and the focus.
    * **Deep sky** (galaxy, nebula, cluster, planetary nebula): the object's
      magnitude does not set the exposure. Sky glow and how long the mount
      holds a star round do. The advice is the longest shutter that stays
      untrailed, a high ISO, and a number of frames to stack. The catalogue's
      magnitude and size only rank it easy, medium or hard, which sets how
      many frames. The f-ratio does not enter.

  Every knob is an option (`advise/2`); `tonight/2` fills them from what the
  telescope is set to. The answer is always a shutter speed and an ISO the
  camera offers, so the page's Use It key can set it.

  What this does not know: how far the mount drifts in a second. Nothing on
  the box measures the residual drift under a hold yet (Lock On measures the
  drift with the motors still, in pixels, to cancel it), so the longest
  untrailed shutter is `max_s:` from the caller, or `drift_arcsec_s:` with
  the star size, or a default of 15 s that the reason names as a default.
  """

  alias Controller.StillCamera.Sidecar

  # the shutter speeds and ISOs the stills camera's Exposure screen offers
  @shutters ~w(1/1000 1/250 1/60 1/15 1/4 1 4 15 30)
  @isos [100, 400, 800, 1600, 3200, 6400]

  # The longest shutter taken to be untrailed when nobody says: on 3 October 2026, at f/10 with
  # 0.1 arcsec/s of drift left, 20 s frames gave 6.1 arcsec stars and 30 s gave 6.5 (#117).
  @max_s 15
  # drift over the exposure of up to this much of the star's width leaves it round: added in
  # quadrature it widens the star by under 8 percent
  @round 0.4
  # a star's width in a picture when it has not been measured, in arcseconds (about the 8SE's on that night)
  @star_arcsec 5.0
  # the f-ratio taken when the optics are not given, and said in the reason
  @assumed_f 10.0

  # Looney 11: a full Moon at f/11 takes 1/ISO, so B = 11² in seconds = N² / (ISO × B)
  @looney 121.0
  # The full Moon's mean surface brightness in mag per square arcsecond: V -12.7 over a disc
  # 1865 arcsec across (2.73 million square arcsec).
  @moon_full 3.4

  # Mean surface brightness of each planet's disc, V mag per square arcsecond: the magnitude at
  # a typical apparition plus 2.5 × log10 of the lit disc's area in square arcseconds. Worked
  # from the standard magnitudes and angular sizes (Astronomical Almanac):
  #
  #   Mercury  V -0.5, 6 arcsec, 60 percent lit           2.6
  #   Venus    V -4.4 at 40 arcsec and 27 percent lit to
  #            V -3.9 at 10 arcsec and full: 1.9 to 0.8   1.3
  #   Mars     V -2.0 at 20 arcsec                        4.1
  #   Jupiter  V -2.7, 47 x 44 arcsec                     5.3
  #   Saturn   V +0.7 for the globe, 19.5 x 17.5 arcsec   6.8
  #   Uranus   V +5.7, 3.7 arcsec                         8.3
  #   Neptune  V +7.8, 2.3 arcsec                         9.4
  #
  # Checked against the night of 3 October 2026 on the 8SE at f/10 (#117): Saturn was taken at
  # 1/40 s ISO 800 and this gives 1/42; a quarter Moon at 1/60 s ISO 100 and this gives 1/60.
  @surface %{
    "sol-mercury" => 2.6,
    "sol-venus" => 1.3,
    "sol-mars" => 4.1,
    "sol-jupiter" => 5.3,
    "sol-saturn" => 6.8,
    "sol-uranus" => 8.3,
    "sol-neptune" => 9.4
  }
  # a planet with no number here: between Jupiter and Saturn, and marked rough
  @surface_unknown 6.0

  # The Moon by how much of it is lit (the same steps as `Ephemeris`'s phase names): stops more
  # than Looney 11, and its name. The classic companions of Looney 11 (f/8 at half, f/5.6 for a
  # crescent) expose for the bright limb.
  @moon_phases [
    {0.97, 0.0, "a full Moon"},
    {0.65, 0.5, "a gibbous Moon"},
    {0.35, 1.0, "a quarter Moon"},
    {0.0, 2.0, "a crescent"}
  ]

  # the ISO each kind is planned around when none is given
  @usual_iso %{moon: 100, planet: 800, star: 800, cluster: 1600, planetary: 1600, galaxy: 3200, nebula: 3200}
  # a stop of ISO away from the usual one costs this many stops of exposure error, when choosing
  # among what the camera offers
  @iso_pull 0.15
  # A stop over counts as this many under, when choosing among what the camera offers: a clipped
  # disc is lost, a dark one can be brightened afterwards.
  @over 2.0

  # deep sky: seconds of light to gather in all, by how hard it is, and the frames that is
  @total_s %{easy: 120, medium: 300, hard: 600}
  @frames 8..120

  @deep [:cluster, :galaxy, :nebula, :planetary]

  @doc "The shutter speeds planned among when `shutters:` is not given (the Exposure screen's)."
  def shutters, do: @shutters

  @doc "The ISOs planned among when `isos:` is not given (the Exposure screen's)."
  def isos, do: @isos

  @doc """
  A starting exposure for `obj` (a catalogue object: `kind`, `mag`, `name`,
  `id`, and `size_arcmin` where the catalogue has it), or nil for a kind
  this has no rule for.

  Options, all of them knobs:

    * `aperture_mm:`, `focal_length_mm:` the telescope, for its f-ratio; or
      `f_ratio:` itself. Without them f/#{trunc(@assumed_f)} is assumed, said in `why`, and
      the answer is `:rough`.
    * `iso:` the ISO to plan around. Given, it is kept and only the shutter
      is chosen. Not given, the ISO and shutter are chosen together from
      what the camera offers, near the kind's usual ISO.
    * `shutters:` the shutter speeds the camera offers, as it words them
      (`"1/60"`, `"4"`); `isos:` the ISOs it offers.
    * `max_s:` the longest untrailed shutter, in seconds. Or
      `drift_arcsec_s:` the drift left under the hold, with `star_arcsec:`
      the width of a star (#{@star_arcsec}): the shutter is then held to the time the
      drift takes to cross #{@round} of a star. Neither: #{@max_s} s.
    * `illumination:` how much of the Moon is lit, 0 to 1. Without it the
      Moon is taken as full, the shortest shutter, and the answer is `:rough`.

  Returns a map:

    * `iso`, `shutter` (as the camera words it), `shutter_s`
    * `frames`: how many to stack, deep sky only
    * `range`: `{faster, slower}`, the shutter speeds worth trying either side
    * `why`: the reason, in a sentence or two
    * `confidence`: `:known` when it follows from the object's surface
      brightness and the telescope's f-ratio (or, deep sky, from a limit that
      was given or measured); `:rough` otherwise
    * `rule`: `:surface`, `:star` or `:deep`
    * `ideal_s`: the shutter the equation asks for at this ISO, before it was
      moved to one the camera offers; `off_stops`: how far the offered pair
      is from it, in stops (negative is darker). Both nil for deep sky
    * `f_ratio`: the one used, nil for deep sky; `max_s`, `max_from`
      (`:given`, `:drift` or `:default`); `ease` (deep sky)
  """
  def advise(obj, opts \\ [])

  def advise(%{kind: :moon}, opts) do
    k = knobs(opts)
    {stops, phase, known?} = moon_phase(opts[:illumination])

    why =
      cond do
        not known? -> "Looney 11 at #{f_words(k.f)}, taken as a full Moon. A thinner phase wants up to two stops more."
        stops == 0.0 -> "Looney 11 at #{f_words(k.f)}: #{phase} at f/11 takes 1/ISO."
        true -> "Looney 11 at #{f_words(k.f)}, #{stops_words(stops)} more for #{phase}."
      end

    bright(:surface, :moon, @looney / :math.pow(2, stops), k, why, known?)
  end

  def advise(%{kind: :planet} = obj, opts) do
    k = knobs(opts)
    surface = @surface[obj[:id]]
    s = surface || @surface_unknown

    why =
      if surface,
        do: "From the surface brightness of #{short_name(obj)}, #{one(s)} mag per square arcsecond, at #{f_words(k.f)}.",
        else: "No surface brightness on file for #{short_name(obj)}: a middling planet's, #{one(s)} mag per square arcsecond, at #{f_words(k.f)}."

    bright(:surface, :planet, brightness(s), k, why, surface != nil)
  end

  def advise(%{kind: :star, mag: mag}, opts) when is_number(mag) do
    k = knobs(opts)
    # the star's light over the disc the air makes of it: a Gaussian's peak is its flux over 1.133 × width²
    s = mag + 2.5 * :math.log10(1.133 * k.star_arcsec * k.star_arcsec)
    why = "Short, to keep a mag #{one(mag)} star round and unclipped at #{f_words(k.f)}. Not a deep exposure."
    bright(:star, :star, brightness(s), k, why, false)
  end

  def advise(%{kind: kind} = obj, opts) when kind in @deep do
    k = knobs(opts)
    allowed = allowed(k)
    {word, s} = List.last(allowed)
    iso = k.iso || nearest_iso(k.isos, @usual_iso[kind])
    ease = ease(obj)
    frames = (@total_s[ease] / s) |> Float.ceil() |> trunc() |> max(@frames.first) |> min(@frames.last)
    {faster, _} = allowed |> Enum.take(-2) |> hd()

    %{
      iso: iso,
      shutter: word,
      shutter_s: s,
      frames: frames,
      range: {faster, word},
      why: "#{limit_words(k)} at ISO #{iso}, #{frames} frames to stack. Sky glow and tracking set this, not its magnitude.",
      confidence: if(k.max_from == :default, do: :rough, else: :known),
      rule: :deep,
      ideal_s: nil,
      off_stops: nil,
      f_ratio: nil,
      max_s: k.max_s,
      max_from: k.max_from,
      ease: ease
    }
  end

  def advise(_, _), do: nil

  @doc """
  `advise/2` with the knobs as this telescope is set: the aperture and focal
  length in Settings (when both are set; the focal length is the one a plate
  solve measured, once one has), and for the Moon how much of it is lit at
  `at:` (now). Any option of `advise/2` given here wins.
  """
  def tonight(obj, opts \\ [])
  def tonight(nil, _opts), do: nil

  def tonight(obj, opts) do
    {at, opts} = Keyword.pop(opts, :at)

    set =
      [aperture_mm: Controller.Settings.get("aperture_mm"), focal_length_mm: Controller.Settings.get("focal_length_mm")]
      |> Enum.filter(fn {_, v} -> is_number(v) and v > 0 end)

    moon = if obj[:kind] == :moon, do: [illumination: Controller.Sky.Ephemeris.moon_phase(at || DateTime.utc_now()).illumination], else: []
    advise(obj, set |> Keyword.merge(moon) |> Keyword.merge(opts))
  end

  @doc "The advice in one line: `\"ISO 800 · 1/60 s\"`, and for deep sky `\"ISO 3200 · 15 s · 40 frames\"`."
  def words(%{iso: iso, shutter: shutter} = advice) do
    ["ISO #{iso}", "#{shutter} s", advice[:frames] && "#{advice.frames} frames"] |> Enum.filter(& &1) |> Enum.join(" · ")
  end

  @doc "The shutter speeds worth trying, in words (`\"1/60 to 1/15 s\"`), or nil when there is only the one."
  def range_words(%{range: {same, same}}), do: nil
  def range_words(%{range: {faster, slower}}), do: "#{faster} to #{slower} s"

  @doc """
  The longest shutter, in seconds, that leaves a star `star_arcsec` wide
  round while the mount drifts `drift_arcsec_s`: the time the drift takes to
  cross #{@round} of the star.

      Exposure.untrailed_s(0.1, 5.0)
      #=> 20.0
  """
  def untrailed_s(drift_arcsec_s, star_arcsec \\ @star_arcsec) when is_number(drift_arcsec_s) and drift_arcsec_s > 0 and is_number(star_arcsec) and star_arcsec > 0,
    do: @round * star_arcsec / drift_arcsec_s

  # -- the discs and the stars: seconds = N² / (ISO × B) ---------------------------------------

  # B for a surface `s` mag per square arcsecond: the full Moon's, scaled by the difference
  defp brightness(s), do: @looney * :math.pow(10, -0.4 * (s - @moon_full))

  defp bright(rule, kind, b, k, why, known?) do
    # ISO × seconds
    product = k.f * k.f / b
    {iso, {word, s}} = choose(product, kind, k)
    ideal = product / iso
    off = :math.log2(iso * s / product)
    # a stop either side of what the equation asks, among what the camera offers, and never without the one chosen
    {faster, _} = Enum.min_by([{word, s}, nearest(ideal / 2, allowed(k))], &elem(&1, 1))
    {slower, _} = Enum.max_by([{word, s}, nearest(ideal * 2, allowed(k))], &elem(&1, 1))

    why =
      [
        why,
        k.f_assumed && "Assumes #{f_words(k.f)}: the telescope's aperture and focal length are not both set.",
        # the tracking limit, not the camera, is what stopped it
        ideal > k.max_s * 1.5 && "Held to #{secs(k.max_s)} s by the tracking limit, #{one(-off)} stops under.",
        # the camera's fastest shutter, and still too much light at this ISO
        off >= 1 and word == elem(hd(allowed(k)), 0) && "#{one(off)} stops over at the fastest shutter: use a lower ISO."
      ]
      |> Enum.filter(& &1)
      |> Enum.join(" ")

    %{
      iso: iso,
      shutter: word,
      shutter_s: s,
      frames: nil,
      range: {faster, slower},
      why: why,
      confidence: if(known? and not k.f_assumed, do: :known, else: :rough),
      rule: rule,
      ideal_s: ideal,
      off_stops: off,
      f_ratio: k.f,
      max_s: k.max_s,
      max_from: k.max_from,
      ease: nil
    }
  end

  # the ISO was given: the offered shutter that misses what it asks for by least, the faster on a tie
  defp choose(product, _kind, %{iso: iso} = k) when is_integer(iso),
    do: {iso, Enum.min_by(allowed(k), fn {_, s} -> Float.round(miss(iso * s / product), 6) end)}

  # not given: the offered pair that misses by least, leaning to the kind's usual ISO; the lower
  # ISO and the faster shutter on a tie
  defp choose(product, kind, k) do
    usual = @usual_iso[kind]

    for(iso <- k.isos, {_, s} = shutter <- allowed(k), do: {miss(iso * s / product) + @iso_pull * abs(:math.log2(iso / usual)), iso, shutter})
    |> Enum.min_by(fn {score, iso, {_, s}} -> {Float.round(score, 6), iso, s} end)
    |> then(fn {_, iso, shutter} -> {iso, shutter} end)
  end

  # how badly an exposure `ratio` times the one asked for misses it, in stops: over counts more than under
  defp miss(ratio) do
    stops = :math.log2(ratio)
    if stops > 0, do: @over * stops, else: -stops
  end

  # the offered shutter nearest `seconds`, in stops; the faster one on a tie
  defp nearest(seconds, allowed), do: Enum.min_by(allowed, fn {_, s} -> Float.round(abs(:math.log2(s / seconds)), 6) end)

  defp nearest_iso(isos, usual), do: Enum.min_by(isos, &abs(:math.log2(&1 / usual)))

  # the offered shutters no longer than the limit, fastest first; the fastest alone when none is
  defp allowed(%{shutters: shutters, max_s: max}) do
    case Enum.filter(shutters, fn {_, s} -> s <= max + 1.0e-9 end) do
      [] -> Enum.take(shutters, 1)
      some -> some
    end
  end

  # -- deep sky: how hard, from the catalogue's magnitude and size, nothing more ---------------

  # Mean surface brightness in mag per square arcsecond, the magnitude spread over the ellipse
  # the catalogue gives. A big bright thing (M31, M42) has a faint mean and a bright middle, so
  # mag 5 or brighter is never called hard.
  defp ease(%{mag: mag, size_arcmin: {a, b}}) when is_number(mag) and mag < 30 and a > 0 and b > 0 do
    surface = mag + 2.5 * :math.log10(:math.pi() / 4 * a * b * 3600)

    cond do
      surface < 19 -> :easy
      surface < 21.5 or mag <= 5 -> :medium
      true -> :hard
    end
  end

  defp ease(%{kind: :planetary}), do: :easy
  defp ease(%{kind: :cluster}), do: :medium
  defp ease(_), do: :hard

  # -- the knobs --------------------------------------------------------------------------------

  defp knobs(opts) do
    {f, assumed} = f_ratio(opts)
    star = positive(opts[:star_arcsec]) || @star_arcsec

    {max_s, max_from} =
      cond do
        positive(opts[:max_s]) -> {opts[:max_s] * 1.0, :given}
        positive(opts[:drift_arcsec_s]) -> {untrailed_s(opts[:drift_arcsec_s], star), :drift}
        true -> {@max_s * 1.0, :default}
      end

    %{
      f: f,
      f_assumed: assumed,
      iso: if(is_integer(opts[:iso]) and opts[:iso] > 0, do: opts[:iso]),
      isos: offered_isos(opts[:isos]),
      shutters: offered_shutters(opts[:shutters]),
      max_s: max_s,
      max_from: max_from,
      drift: positive(opts[:drift_arcsec_s]),
      star_arcsec: star
    }
  end

  defp f_ratio(opts) do
    cond do
      positive(opts[:f_ratio]) -> {opts[:f_ratio] * 1.0, false}
      positive(opts[:aperture_mm]) && positive(opts[:focal_length_mm]) -> {opts[:focal_length_mm] / opts[:aperture_mm], false}
      true -> {@assumed_f, true}
    end
  end

  # as the camera words them, with their seconds, fastest first; "Bulb" and anything unreadable dropped
  defp offered_shutters(list) do
    case for(w <- list || [], s = Sidecar.seconds(w), is_number(s) and s > 0, do: {to_string(w), s}) |> Enum.sort_by(&elem(&1, 1)) do
      [] -> offered_shutters(@shutters)
      some -> some
    end
  end

  defp offered_isos(list) do
    case list |> List.wrap() |> Enum.filter(&(is_integer(&1) and &1 > 0)) |> Enum.sort() do
      [] -> @isos
      some -> some
    end
  end

  defp positive(x) when is_number(x) and x > 0, do: x
  defp positive(_), do: nil

  # -- words ------------------------------------------------------------------------------------

  defp moon_phase(k) when is_number(k) do
    {_, stops, name} = Enum.find(@moon_phases, fn {least, _, _} -> k >= least end) || List.last(@moon_phases)
    {stops, name, true}
  end

  defp moon_phase(_), do: {0.0, "a full Moon", false}

  defp limit_words(%{max_from: :default, max_s: s}), do: "The longest shutter under the #{secs(s)} s default tracking limit"
  defp limit_words(%{max_from: :drift, max_s: s, drift: d}), do: "The longest shutter the measured drift (#{two(d)} arcsec/s) keeps round, #{secs(s)} s or less"
  defp limit_words(%{max_s: s}), do: "The longest shutter under the #{secs(s)} s tracking limit"

  defp stops_words(0.5), do: "half a stop"
  defp stops_words(1.0), do: "one stop"
  defp stops_words(2.0), do: "two stops"
  defp stops_words(n), do: "#{one(n)} stops"

  # "Moon · last quarter" is the Moon; "M31 Andromeda" is itself
  defp short_name(%{name: name}) when is_binary(name), do: name |> String.split(" · ", parts: 2) |> hd()
  defp short_name(_), do: "this planet"

  # "f/10", "f/6.3"
  defp f_words(f), do: "f/#{if abs(f - round(f)) < 0.05, do: round(f), else: one(f)}"

  defp secs(s), do: if(abs(s - round(s)) < 0.05, do: "#{round(s)}", else: one(s))
  defp one(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp two(x), do: :erlang.float_to_binary(x / 1, decimals: 2)
end
