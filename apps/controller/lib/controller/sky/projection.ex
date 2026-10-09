defmodule Controller.Sky.Projection do
  @moduledoc """
  Ways to draw the sky flat, each a chart an astronomer would recognise:

    * **Dome** (`:dome`): the whole sky overhead, as if lying on your back:
      the zenith in the middle, the horizon the rim, north up, east on the
      left (a stereographic projection: shapes stay true, so constellations
      look like themselves).
    * **Horizon** (`:horizon`): the hemisphere flattened, as if standing and
      turning round once: bearing across (east, south, west, from the left;
      north in the middle for a site south of the equator), altitude up, the
      horizon a straight line with the tree line along it.
    * **Mount** (`:mount`): the chart big telescopes show, in the mount's own
      axes: hour angle across, the meridian down the middle (rising on the
      left, setting on the right), declination up, the pole at the top. The
      horizon is a curve, and a target's night is a straight line along it.

  Every position comes in as a direction with both its horizontal and its
  equatorial coordinates (`dir/3`), so each chart takes what it needs. A
  chart is in degrees on both axes (the dome in its own unit circle, ×100),
  so a degree is the same size everywhere on a flat chart.
  """

  alias Controller.Sky.Astro

  @deg :math.pi() / 180
  # the horizon chart stretches altitude, as flat horizon charts do: 360° by 90° would be a thin strip
  @alt_x 1.8

  @doc "The charts, in the order they're offered: `{key, name, what it is}`."
  def views do
    [
      {"dome", "Dome", "The sky overhead, the horizon all round"},
      {"horizon", "Horizon", "Standing and turning round: bearing across, altitude up"},
      {"mount", "Mount", "The mount's axes: hour angle across, declination up"}
    ]
  end

  @doc "A view from its key, the dome when it's not one."
  def view("horizon"), do: :horizon
  def view("mount"), do: :mount
  def view(:horizon), do: :horizon
  def view(:mount), do: :mount
  def view(_), do: :dome

  @doc """
  A direction on the sky from `ra`/`dec` (degrees), seen from `ctx`
  (`%{lat, lst}`): `%{ra, dec, ha, alt, az}`.
  """
  def dir(ra, dec, %{lat: lat, lst: lst}) do
    {alt, az} = Astro.alt_az(ra, dec, lat, lst)
    %{ra: ra, dec: dec, ha: Astro.hour_angle(lst, ra), alt: alt, az: az}
  end

  @doc "A direction from a horizontal one (`alt`, `az` degrees)."
  def dir_altaz(alt, az, %{lat: lat, lst: lst}) do
    {ra, dec} = Astro.radec_from_altaz(alt, az, lat, lst)
    %{ra: ra, dec: dec, ha: Astro.hour_angle(lst, ra), alt: alt, az: az}
  end

  # -- the frame -------------------------------------------------------------------------

  @doc """
  The chart's extent and shape: `%{view_box, shape}` (`:disc` for the dome,
  `:rect` for the flat charts). The Mount chart reaches down only as far as a
  star can rise from `site` (no point drawing the sky that never comes up).
  """
  def frame(:dome, _site), do: %{view_box: "-104 -104 208 208", shape: :disc, x: -104, y: -104, w: 208, h: 208}
  def frame(:horizon, _site) do
    top = -90 * @alt_x
    %{view_box: "-184 #{top - 8} 368 #{-top + 20}", shape: :rect, x: -184, y: top - 8, w: 368, h: -top + 20, top: top, bottom: 0}
  end

  def frame(:mount, %{lat: lat}) do
    low = Float.round(lowest_dec(lat) * 1.0, 1)
    # the chart from the pole (or the lowest that rises) to the lowest that rises (or the pole)
    {top, bottom} = if lat >= 0, do: {-90, -low}, else: {-low, 90}
    pad_t = 10
    pad_b = 14
    %{view_box: "-196 #{top - pad_t} 392 #{bottom - top + pad_t + pad_b}", shape: :rect, x: -196, y: top - pad_t, w: 392, h: bottom - top + pad_t + pad_b, top: top, bottom: bottom}
  end

  # the furthest declination from the visible pole that still rises
  defp lowest_dec(lat) when lat >= 0, do: max(lat - 90, -90) - 2
  defp lowest_dec(lat), do: min(lat + 90, 90) + 2

  # -- placing ---------------------------------------------------------------------------

  @doc """
  Where a direction lands on the chart: `{x, y}`, or nil when the chart
  doesn't show it (below the horizon on the dome and the horizon chart; never
  for the mount chart, where the horizon is drawn instead).
  """
  def xy(:dome, %{alt: alt, az: az}, _site) when alt > -2 do
    {x, y} = Astro.project(alt, az)
    {x * 100, y * 100}
  end

  def xy(:dome, _, _), do: nil

  def xy(:horizon, %{alt: alt, az: az}, site) when alt > -4 do
    {norm180(az - facing(site)), -min(alt, 90.0) * @alt_x}
  end

  def xy(:horizon, _, _), do: nil
  def xy(:mount, %{ha: ha, dec: dec}, _site), do: {ha * 1.0, -dec * 1.0}

  # the horizon chart faces the equator: south from the north, north from the south
  defp facing(%{lat: lat}) when lat < 0, do: 0.0
  defp facing(_), do: 180.0

  @doc """
  A line through directions as SVG point lists: one per stretch that stays
  on the chart, broken where it leaves it or wraps round a flat chart's edge
  (east to west of the horizon chart, ±12 h on the mount chart).
  """
  def polylines(view, dirs, site) do
    dirs
    |> Enum.map(&xy(view, &1, site))
    |> runs(view)
    |> Enum.filter(&(length(&1) > 1))
    |> Enum.map(&points/1)
  end

  # stretches of placed points; a gap (nil) or a jump across the seam starts a new one
  defp runs(pts, view) do
    pts
    |> Enum.reduce({[], []}, fn
      nil, {cur, acc} -> {[], push(cur, acc)}
      p, {[], acc} -> {[p], acc}
      {x, _} = p, {[{px, _} | _] = cur, acc} -> if seam?(view, x, px), do: {[p], push(cur, acc)}, else: {[p | cur], acc}
    end)
    |> then(fn {cur, acc} -> push(cur, acc) end)
    |> Enum.reverse()
  end

  defp push([], acc), do: acc
  defp push(cur, acc), do: [Enum.reverse(cur) | acc]

  defp seam?(:dome, _, _), do: false
  defp seam?(_, x, px), do: abs(x - px) > 180

  @doc "Points as an SVG `points` value."
  def points(pts), do: Enum.map_join(pts, " ", fn {x, y} -> "#{r1(x)},#{r1(y)}" end)

  # -- the grid ---------------------------------------------------------------------------

  @doc """
  What each chart draws before the sky: `%{lines: [%{points, class}], labels:
  [%{x, y, text, class, anchor}], fills: [%{points, class}]}`. The dome:
  altitude rings, the compass. The horizon chart: altitude lines, the
  compass along the bottom. The mount chart: an hour and 15° grid, the
  meridian, the pole, right ascension along the top, and the horizon as a
  curve with what's below it shaded. All three draw the celestial equator and
  the ecliptic.
  """
  def grid(view, site, ctx) do
    base = grid_for(view, site, ctx)
    sky = [line(view, equator(ctx), site, "equator"), line(view, ecliptic(ctx), site, "ecliptic")]
    Map.update!(base, :lines, &(&1 ++ List.flatten(sky)))
  end

  defp line(view, dirs, site, class), do: for(p <- polylines(view, dirs, site), do: %{points: p, class: class})

  defp grid_for(:dome, _site, _ctx) do
    rings =
      for alt <- [30, 60] do
        r = 100 * :math.tan((90 - alt) / 2 * @deg) / :math.tan(45 * @deg)
        %{points: points(for(a <- 0..360//6, do: {r * :math.cos(a * @deg), r * :math.sin(a * @deg)})), class: "alt"}
      end

    %{
      fills: [],
      lines: rings ++ [%{points: "-100,0 100,0", class: "axis"}, %{points: "0,-100 0,100", class: "meridian"}],
      labels: [
        %{x: 0, y: -101.5, text: "N", class: "card", anchor: "middle"},
        %{x: 0, y: 103.5, text: "S", class: "card", anchor: "middle"},
        %{x: -102, y: 1, text: "E", class: "card", anchor: "end"},
        %{x: 102, y: 1, text: "W", class: "card", anchor: "start"}
      ]
    }
  end

  defp grid_for(:horizon, site, _ctx) do
    face = facing(site)
    alts = for a <- [30, 60], do: %{points: "-180,#{-a * @alt_x} 180,#{-a * @alt_x}", class: "alt"}

    bearings =
      for {name, az} <- [{"N", 0}, {"NE", 45}, {"E", 90}, {"SE", 135}, {"S", 180}, {"SW", 225}, {"W", 270}, {"NW", 315}] do
        x = norm180(az - face)
        {name, x}
      end

    %{
      fills: [],
      lines:
        [%{points: "-180,0 180,0", class: "horizon-line"}] ++
          alts ++ for({_, x} <- bearings, abs(x) < 179.9, do: %{points: "#{r1(x)},0 #{r1(x)},#{-90 * @alt_x}", class: "bearing"}),
      labels:
        for({name, x} <- bearings, abs(x) < 179.9, do: %{x: r1(x), y: 11, text: name, class: "card", anchor: "middle"}) ++
          for(a <- [30, 60], do: %{x: -178, y: r1(-a * @alt_x - 2), text: "#{a}°", class: "tick", anchor: "start"})
    }
  end

  defp grid_for(:mount, site, ctx) do
    %{top: top, bottom: bottom} = frame(:mount, site)
    hours = for h <- -12..12, do: h * 15

    vertical =
      for x <- hours do
        %{points: "#{x},#{top} #{x},#{bottom}", class: if(x == 0, do: "meridian", else: if(rem(x, 45) == 0, do: "hour major", else: "hour"))}
      end

    decs = for d <- -75..90//15, -d >= top and -d <= bottom, do: d
    horizontal = for d <- decs, do: %{points: "-180,#{-d} 180,#{-d}", class: if(d == 0, do: "dec major", else: "dec")}

    # the horizon as a curve in the mount's axes, and below it shaded
    horizon = for ha <- -180..180//3, do: {ha * 1.0, -horizon_dec(ha, site.lat)}
    below = if site.lat >= 0, do: horizon ++ [{180.0, bottom * 1.0}, {-180.0, bottom * 1.0}], else: horizon ++ [{180.0, top * 1.0}, {-180.0, top * 1.0}]

    # 30° up (airmass 2): where a target is worth the time
    alt30 = for(az <- 0..360//4, do: dir_altaz(30.0, az * 1.0, ctx)) |> then(&polylines(:mount, &1, site))

    ha_labels =
      for h <- -12..12//3 do
        text = cond do
          h == 0 -> "0h meridian"
          h > 0 -> "+#{h}h"
          true -> "#{h}h"
        end

        %{x: h * 15, y: bottom + 10, text: text, class: "tick", anchor: "middle"}
      end

    ra_labels =
      for h <- -12..12//3, h not in [-12, 12] do
        ra = :math.fmod(:math.fmod(ctx.lst - h * 15, 360) + 360, 360)
        %{x: h * 15, y: top - 3, text: "RA #{round(ra / 15) |> rem(24)}h", class: "tick ra", anchor: "middle"}
      end

    dec_labels = for d <- decs, d != 90, do: %{x: -194, y: -d + 1.2, text: "#{if d > 0, do: "+"}#{d}°", class: "tick", anchor: "start"}

    %{
      fills: [%{points: points(below), class: "below"}],
      lines:
        vertical ++ horizontal ++
          [%{points: points(horizon), class: "horizon-line"}] ++ for(p <- alt30, do: %{points: p, class: "alt30"}),
      labels: ha_labels ++ ra_labels ++ dec_labels ++ [%{x: 0, y: if(site.lat >= 0, do: top + 6, else: bottom - 3), text: "pole", class: "tick pole", anchor: "middle"}]
    }
  end

  # the declination on the horizon at an hour angle (alt 0): tan δ = -cos H / tan φ
  defp horizon_dec(ha, lat) when abs(lat) < 0.01, do: if(abs(norm180(ha)) < 90, do: 90.0, else: -90.0)
  defp horizon_dec(ha, lat), do: :math.atan(-:math.cos(ha * @deg) / :math.tan(lat * @deg)) / @deg

  # the celestial equator and the ecliptic, as directions
  defp equator(ctx), do: for(ra <- 0..360//4, do: dir(ra * 1.0, 0.0, ctx))

  defp ecliptic(ctx) do
    e = 23.4393 * @deg

    for l <- 0..360//4 do
      lam = l * @deg
      ra = :math.atan2(:math.sin(lam) * :math.cos(e), :math.cos(lam)) / @deg
      dec = :math.asin(:math.sin(e) * :math.sin(lam)) / @deg
      dir(:math.fmod(ra + 360, 360), dec, ctx)
    end
  end

  @doc """
  A moving object's directions as chart lines, cut wherever it is below the
  horizon (the mount chart draws the sky below the horizon too, so there the
  cut is explicit).
  """
  def path_lines(view, dirs, site) do
    dirs = Enum.map(dirs, &if(&1.alt > 0, do: &1, else: Map.put(&1, :alt, -90.0)))

    case view do
      :mount -> dirs |> Enum.map(&if(&1.alt < -1, do: nil, else: xy(:mount, &1, site))) |> runs(:mount) |> Enum.filter(&(length(&1) > 1)) |> Enum.map(&points/1)
      _ -> polylines(view, dirs, site)
    end
  end

  defp norm180(x), do: Astro.norm180(x)
  defp r1(x), do: Float.round(x * 1.0, 1)
end
