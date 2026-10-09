defmodule Controller.Components.Visibility do
  @moduledoc """
  The plot observers plan a night with: altitude against time, dusk to
  dawn, a line for each of tonight's best targets. Where it peaks is when to
  look (it's labelled there, by its number in the list), the shaded bands are
  day and twilight, the vertical line is the time being shown. A line is
  dimmed while its target is behind the trees (the tree line at the bearing
  it's at then), so "it's up but behind the oak" reads at a glance.

  Lines are told apart by their dash and their label, never by colour alone,
  so night mode's all-red still reads.

      <.plot targets={top} site={@site} at={@at} utc_offset_min={@utc_offset_min} horizon={@horizon} />
  """
  use Phoenix.Component

  alias Controller.Settings
  alias Controller.Sky.{Astro, Ephemeris}

  @step_min 10
  # the plot's width: minutes across 360 units
  @w 360
  @dashes ["", "6 3", "2 2", "8 3 2 3", "1 3", "10 4"]

  attr :targets, :list, required: true, doc: "objects with `id`, `name`, `ra_deg`, `dec_deg`, best first"
  attr :site, :map, required: true
  attr :at, :any, required: true, doc: "the time being shown"
  attr :utc_offset_min, :any, default: nil
  attr :horizon, :any, default: nil, doc: "the tree line (nil: the real horizon)"

  def plot(assigns) do
    {start, stop} = window(assigns.at, assigns.site)
    minutes = div(DateTime.diff(stop, start), 60)
    x = fn t -> Float.round(DateTime.diff(t, start) / 60 / minutes * @w, 1) end
    times = for m <- 0..minutes//@step_min, do: DateTime.add(start, m * 60, :second)

    lines =
      assigns.targets
      |> Enum.with_index(1)
      |> Enum.map(fn {o, i} -> line(o, i, times, x, assigns.site, assigns.horizon) end)

    single = length(lines) == 1
    off = (assigns.utc_offset_min || 0) * 60

    assigns =
      assign(assigns,
        single: single,
        lines: lines,
        # one object: its highest point said in words; several: each line's number
        peaks: if(single, do: Enum.map(peaks(lines), &Map.put(&1, :n, "#{hd(lines).peak_words} at #{Calendar.strftime(DateTime.add(hd(lines).peak_t, off, :second), "%H:%M")}")), else: peaks(lines)),
        bands: bands(times, x, assigns.site),
        ticks: ticks(start, stop, x, assigns.utc_offset_min),
        now_x: x.(assigns.at),
        show_now: DateTime.compare(assigns.at, start) != :lt and DateTime.compare(assigns.at, stop) != :gt
      )

    # The lines are SVG stretched to the box (strokes stay hairlines); every
    # word is HTML placed by percent on top, so it stays 12 px at any width.
    ~H"""
    <figure :if={@targets != []} class="visibility">
      <div class="vis-plot" role="img" aria-label={"Altitude through the night for " <> Enum.map_join(@lines, ", ", &"#{&1.name}, highest #{&1.peak_words}")}>
        <svg viewBox="0 -90 360 90" preserveAspectRatio="none" aria-hidden="true">
          <rect :for={b <- @bands} x={b.x} y="-90" width={b.w} height="90" class={["vis-band", b.class]} />
          <line :for={a <- [30, 60]} x1="0" y1={-a} x2="360" y2={-a} class="vis-grid" />
          <line x1="0" y1="0" x2="360" y2="0" class="vis-axis" />
          <g :for={l <- @lines} class="vis-line">
            <polyline :for={p <- l.behind} points={p} class="vis-behind" stroke-dasharray={l.dash} />
            <polyline :for={p <- l.clear} points={p} class="vis-clear" stroke-dasharray={l.dash} />
          </g>
          <line :if={@show_now} x1={@now_x} y1="-90" x2={@now_x} y2="0" class="vis-now" />
        </svg>
        <span :for={a <- [30, 60]} class="vis-y" style={"top: #{pct((90 - a) / 90 * 360)}%"} aria-hidden="true">{a}°</span>
        <span :for={t <- @ticks} class="vis-x" style={"left: #{pct(t.x)}%"} aria-hidden="true">{t.text}</span>
        <span :for={p <- @peaks} class={["vis-peak", p.edge, @single && "vis-peak-words"]} style={"left: #{pct(p.x)}%; top: #{p.top}%"} aria-hidden="true">{p.n}</span>
      </div>
      <ul :if={!@single} class="vis-keys" aria-hidden="true">
        <li :for={l <- @lines}>
          <svg viewBox="0 0 24 4" width="24" height="4" aria-hidden="true"><line x1="0" y1="2" x2="24" y2="2" stroke-dasharray={l.dash} /></svg>
          <b>{l.n}</b> {l.short}
        </li>
      </ul>
      <figcaption class="dim">{if @single, do: "Its altitude through the night, dusk to dawn.", else: "Altitude through the night, dusk to dawn: when each is highest."} Shaded: day and twilight. Dimmed: behind the trees.</figcaption>
    </figure>
    """
  end

  # 0..360 plot units as a percentage of the box
  defp pct(x), do: Float.round(x / @w * 100, 2)

  # each line's number at its highest point, nudged so two peaks close together don't cover each other
  defp peaks(lines) do
    lines
    |> Enum.filter(& &1.peak)
    |> Enum.sort_by(fn l -> elem(l.peak, 0) end)
    |> Enum.reduce([], fn l, placed ->
      {x, y} = l.peak
      top = Enum.reduce_while(1..4, (90 + y) / 90 * 100, fn _, top ->
        if Enum.any?(placed, &(abs(&1.x - x) < 14 and abs(&1.top - top) < 14)),
          do: {:cont, if(top > 20, do: top - 14, else: top + 14)},
          else: {:halt, top}
      end)

      edge = cond do
        x < 8 -> "at-start"
        x > 352 -> "at-end"
        true -> nil
      end

      [%{n: l.n, x: x, top: Float.round(top * 1.0, 1), edge: edge} | placed]
    end)
  end

  # from an hour before dark (or now, if it's dark already) to just after dawn, at most 14 h
  defp window(at, site) do
    sun = fn t -> Ephemeris.sun_alt(t, site) end
    probe = for m <- 0..(24 * 60)//@step_min, do: DateTime.add(at, m * 60, :second)

    start =
      if sun.(at) > -6.0 do
        dusk = Enum.find(probe, &(sun.(&1) < -6.0)) || at
        DateTime.add(dusk, -3600, :second)
      else
        DateTime.add(at, -3600, :second)
      end

    after_start = for m <- 60..(14 * 60)//@step_min, do: DateTime.add(start, m * 60, :second)
    dawn = Enum.find(after_start, &(sun.(&1) > -6.0)) || DateTime.add(start, 14 * 3600, :second)
    {start, DateTime.add(dawn, 1800, :second)}
  end

  # one target: its altitude each step, split where it's clear and where it's behind the trees
  defp line(o, i, times, x, site, horizon) do
    samples =
      for t <- times do
        {alt, az} = Astro.alt_az(o.ra_deg, o.dec_deg, site.lat, Astro.lst_deg(t, site.lon))
        tree = if horizon, do: Settings.horizon_at(horizon, az), else: 0.0
        {x.(t), Float.round(-max(alt, 0.0) * 1.0, 1), alt, alt > tree, t}
      end

    up = Enum.filter(samples, fn {_, _, alt, _, _} -> alt > 0 end)
    peak = Enum.max_by(up, fn {_, _, alt, _, _} -> alt end, fn -> nil end)

    %{
      n: i,
      name: o.name,
      short: o.name |> String.split(" ") |> List.first(),
      dash: Enum.at(@dashes, rem(i - 1, length(@dashes))),
      clear: runs(samples, fn {_, _, alt, clear, _} -> alt > 0 and clear end),
      behind: runs(samples, fn {_, _, alt, _, _} -> alt > 0 end),
      peak: peak && {elem(peak, 0), elem(peak, 1)},
      peak_t: peak && elem(peak, 4),
      peak_words: if(peak, do: "#{round(elem(peak, 2))}°", else: "not up")
    }
  end

  defp runs(samples, keep?) do
    samples
    |> Enum.chunk_by(keep?)
    |> Enum.filter(fn [s | _] = run -> keep?.(s) and length(run) > 1 end)
    |> Enum.map(fn run -> Enum.map_join(run, " ", fn {x, y, _, _, _} -> "#{x},#{y}" end) end)
  end

  # day and the twilights, shaded: the sun's height each step, grouped
  defp bands(times, x, site) do
    times
    |> Enum.map(fn t -> {t, sky_class(Ephemeris.sun_alt(t, site))} end)
    |> Enum.chunk_by(&elem(&1, 1))
    |> Enum.reject(fn [{_, c} | _] -> c == "night" end)
    |> Enum.map(fn [{t0, c} | _] = run ->
      {t1, _} = List.last(run)
      x0 = x.(t0)
      %{x: x0, w: max(Float.round(x.(t1) - x0 + 360 / max(length(times) - 1, 1), 1), 0.5), class: c}
    end)
  end

  defp sky_class(sun) when sun > 0, do: "day"
  defp sky_class(sun) when sun > -12, do: "twilight"
  defp sky_class(sun) when sun > -18, do: "dusk"
  defp sky_class(_), do: "night"

  # the hours along the bottom, in the viewer's own time when it's known
  defp ticks(start, stop, x, offset) do
    off = (offset || 0) * 60
    local = DateTime.add(start, off, :second)
    first = DateTime.add(start, (60 - local.minute) * 60 - local.second, :second)

    Stream.iterate(first, &DateTime.add(&1, 3600, :second))
    |> Enum.take_while(&(DateTime.compare(&1, stop) != :gt))
    |> Enum.filter(fn t -> rem(DateTime.add(t, off, :second).hour, 2) == 0 end)
    |> Enum.map(fn t -> %{x: x.(t), text: Calendar.strftime(DateTime.add(t, off, :second), "%H:%M")} end)
  end
end
