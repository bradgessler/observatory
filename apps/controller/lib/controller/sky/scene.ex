defmodule Controller.Sky.Scene do
  @moduledoc """
  The sky at one moment from one site, laid out on one chart
  (`Controller.Sky.Projection`): the stars, the planets, the Moon and the
  deep-sky objects where they land, the constellation lines, the tree line,
  and the chart's own grid. Pure: built once a tick by a page (the Sky Map,
  the Scope page) and drawn by `Controller.Components.SkyChart`.

      Scene.build(DateTime.utc_now(), site, horizon, view: :mount)
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Catalog, Ephemeris, Projection}

  @mag_limit 5.0

  @doc """
  Options: `view:` (`:dome`, `:horizon`, `:mount`), `trees:` (whether a tree
  line was given; without one the sky goes down to the real horizon and
  nothing is dimmed), `sky:` (false for a chart of the frame alone, the grid
  and the trees, with no stars: an object's night, see `night_path/4`).
  """
  def build(%DateTime{} = at, site, horizon, opts \\ []) do
    view = Projection.view(Keyword.get(opts, :view, :dome))
    trees? = Keyword.get(opts, :trees, true)
    sky? = Keyword.get(opts, :sky, true)
    lst = Astro.lst_deg(at, site.lon)
    ctx = %{lat: site.lat, lst: lst}

    place = fn o ->
      d = Projection.dir(o.ra_deg, o.dec_deg, ctx)

      case Projection.xy(view, d, site) do
        nil ->
          nil

        {x, y} ->
          low = if trees?, do: Settings.horizon_at(horizon, d.az), else: 0.0
          Map.merge(o, %{alt: d.alt, az: d.az, ha: d.ha, x: x, y: y, hidden: d.alt < low})
      end
    end

    stars = if sky?, do: for(o <- Catalog.stars(@mag_limit), o = place.(o), o, do: o), else: []
    sol = if sky?, do: for(o <- Ephemeris.objects(at, site), o = place.(o), o, do: o), else: []
    dsos = if sky?, do: sol ++ for(o <- Catalog.dsos(), o.mag < 10, o = place.(o), o, do: o), else: []

    lines =
      for line <- if(sky?, do: Catalog.lines(), else: []),
          dirs = Enum.map(line, fn {ra, dec} -> Projection.dir(ra, dec, ctx) end),
          # on the dome and the horizon chart, only the figures that are up
          view == :mount or Enum.all?(dirs, &(&1.alt > -3)),
          p <- Projection.polylines(view, dirs, site),
          do: p

    # the Sun, where it lands, and how dark the sky is because of it
    sun_dir = with %{ra_deg: ra, dec_deg: dec} <- Ephemeris.position(:sun, at), do: Projection.dir(ra, dec, ctx)
    {phase, _} = Controller.Sky.Daylight.phase(sun_dir.alt)

    sun =
      case sky? && sun_dir.alt > -1 && Projection.xy(view, sun_dir, site) do
        {x, y} -> %{x: x, y: y, alt: sun_dir.alt, az: sun_dir.az}
        _ -> nil
      end

    tree_dirs = for az <- 0..360//5, do: Projection.dir_altaz(max(Settings.horizon_at(horizon, az * 1.0), 0.0), az * 1.0, ctx)

    %{
      view: view,
      at: at,
      lst: lst,
      site: site,
      frame: Projection.frame(view, site),
      grid: Projection.grid(view, site, ctx),
      stars: stars,
      dsos: dsos,
      lines: lines,
      sun: sun,
      # a chart without the sky (an object's night) isn't of one moment, so it isn't tinted by one
      phase: if(sky?, do: phase),
      trees: trees?,
      tree_line: if(trees?, do: Projection.polylines(view, tree_dirs, site), else: []),
      # how high the trees reach by direction, for anything placed later (nil: the real horizon)
      horizon: if(trees?, do: horizon),
      tree_fill: if(trees?, do: tree_fill(view, tree_dirs, site), else: nil),
      ctx: ctx
    }
  end

  # what's behind the trees, shaded: on the dome the rim to the tree line; on
  # the horizon chart the strip under it; the mount chart draws the tree line
  # as a curve over the shaded below-the-horizon region
  defp tree_fill(:dome, dirs, site) do
    pts = Enum.map(dirs, &Projection.xy(:dome, &1, site)) |> Enum.reject(&is_nil/1)
    "M100,0 A100,100 0 1,1 -100,0 A100,100 0 1,1 100,0 Z M" <> Projection.points(pts) <> " Z"
  end

  defp tree_fill(:horizon, dirs, site) do
    pts = dirs |> Enum.map(&Projection.xy(:horizon, &1, site)) |> Enum.reject(&is_nil/1) |> Enum.sort_by(&elem(&1, 0))
    "M-180,0 L" <> Projection.points(pts) <> " L180,0 Z"
  end

  defp tree_fill(:mount, _dirs, _site), do: nil

  @doc "Where a direction (RA/Dec degrees) lands on the scene's chart: `{x, y}` or nil."
  def place(%{view: view, site: site, ctx: ctx}, ra, dec), do: Projection.xy(view, Projection.dir(ra, dec, ctx), site)

  @doc "The direction itself, with its altitude and bearing: `%{ra, dec, ha, alt, az}`."
  def dir(%{ctx: ctx}, ra, dec), do: Projection.dir(ra, dec, ctx)

  @doc """
  A ring `r` degrees round (RA/Dec) on the chart, true to size wherever it
  is: the telescope's margin. SVG point lists (a ring can wrap a flat chart's edge).
  """
  def ring(%{view: view, site: site, ctx: ctx}, ra, dec, r) do
    d0 = Projection.dir(ra, dec, ctx)
    deg = :math.pi() / 180
    {a, z, rr} = {d0.alt * deg, d0.az * deg, r * deg}

    dirs =
      for b <- 0..360//12 do
        b = b * deg
        a2 = :math.asin(:math.sin(a) * :math.cos(rr) + :math.cos(a) * :math.sin(rr) * :math.cos(b))
        z2 = z + :math.atan2(:math.sin(b) * :math.sin(rr) * :math.cos(a), :math.cos(rr) - :math.sin(a) * :math.sin(a2))
        Projection.dir_altaz(a2 / deg, z2 / deg, ctx)
      end

    Projection.polylines(view, dirs, site)
  end

  @step_min 10

  @doc """
  One object's night on the scene's chart, from the scene's moment to the
  coming dawn (when it is day, that is through the whole night ahead):

    * `segments`: its path as chart lines, each `%{points, class}` with the
      class `"dark"` (the sun 18° or more below the horizon), `"twilight"`
      or `"day"`, so a page can draw where it can be seen differently from
      where it can't;
    * `hours`: where it is at each whole hour (the viewer's time) while it's
      up, `%{x, y, label, class}`;
    * `now`: where it is at the scene's moment, `%{x, y}`, or nil when it's down;
    * `classes`: which of the three the path passes through, for a legend.
  """
  def night_path(%{view: view, site: site, at: at} = scene, ra, dec, utc_offset_min \\ nil) do
    until = dawn_after(at, site)
    minutes = div(DateTime.diff(until, at), 60)

    samples =
      for m <- 0..minutes//@step_min do
        t = DateTime.add(at, m * 60, :second)
        d = Projection.dir(ra, dec, %{lat: site.lat, lst: Astro.lst_deg(t, site.lon)})
        {d, {sun_class(Ephemeris.sun_alt(t, site)), behind?(scene, d)}}
      end

    # stretches of one class; each also takes the next one's first point, so the line doesn't break between them
    segments =
      samples
      |> Enum.chunk_by(&elem(&1, 1))
      |> then(fn runs -> Enum.zip(runs, tl(runs) ++ [[]]) end)
      |> Enum.flat_map(fn {run, next} ->
        {class, behind} = run |> hd() |> elem(1)
        dirs = Enum.map(run ++ Enum.take(next, 1), &elem(&1, 0))
        for p <- Projection.path_lines(view, dirs, site), do: %{points: p, class: class, behind: behind}
      end)

    now =
      case samples do
        [{%{alt: alt} = d, _} | _] when alt > 0 ->
          case Projection.xy(view, d, site) do
            {x, y} -> %{x: x, y: y}
            nil -> nil
          end

        _ ->
          nil
      end

    %{
      segments: segments,
      hours: hours(scene, at, until, ra, dec, utc_offset_min),
      now: now,
      classes: samples |> Enum.filter(&(elem(&1, 0).alt > 0)) |> Enum.map(&elem(elem(&1, 1), 0)) |> Enum.uniq(),
      until: until
    }
  end

  # under the tree line in that direction (with no tree line given, nothing is)
  defp behind?(%{horizon: nil}, _), do: false
  defp behind?(%{horizon: horizon}, %{alt: alt, az: az}), do: alt > 0 and alt < Settings.horizon_at(horizon, az)
  defp behind?(_, _), do: false

  defp sun_class(sun) when sun > 0, do: "day"
  defp sun_class(sun) when sun > -18, do: "twilight"
  defp sun_class(_), do: "dark"

  # the end of the night ahead: the first time after full dark that the sky starts to brighten;
  # where it never gets fully dark (a high-latitude summer), twelve hours on
  defp dawn_after(at, site) do
    probe = for m <- 0..(26 * 60)//@step_min, do: DateTime.add(at, m * 60, :second)
    {_, dawn} =
      Enum.reduce_while(probe, {false, nil}, fn t, {dark?, _} ->
        night? = Ephemeris.sun_alt(t, site) <= -18
        cond do
          night? -> {:cont, {true, nil}}
          dark? -> {:halt, {true, t}}
          true -> {:cont, {false, nil}}
        end
      end)

    dawn || DateTime.add(at, 12 * 3600, :second)
  end

  # each whole hour of the viewer's time between now and dawn, where it is while it's up
  defp hours(%{view: view, site: site} = scene, at, until, ra, dec, offset) do
    off = (offset || 0) * 60
    local = DateTime.add(at, off, :second)
    first = DateTime.add(at, (60 - local.minute) * 60 - local.second, :second)

    Stream.iterate(first, &DateTime.add(&1, 3600, :second))
    |> Enum.take_while(&(DateTime.compare(&1, until) != :gt))
    |> Enum.flat_map(fn t ->
      d = Projection.dir(ra, dec, %{lat: site.lat, lst: Astro.lst_deg(t, site.lon)})

      case d.alt > 0 && Projection.xy(view, d, site) do
        {x, y} -> [%{x: x, y: y, label: Calendar.strftime(DateTime.add(t, off, :second), "%H:%M"), class: sun_class(Ephemeris.sun_alt(t, site)), behind: behind?(scene, d)}]
        _ -> []
      end
    end)
  end
end
