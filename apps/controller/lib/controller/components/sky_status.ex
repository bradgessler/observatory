defmodule Controller.Components.SkyStatus do
  @moduledoc """
  The Sky section's status, in the toolbar of the Sky Map and Tonight: the
  time the sky is drawn for (an hour either way, back to now), how dark the
  sky is then (a solar graph and the phase's name, `Controller.Sky.Daylight`),
  and where it's drawn from (the location and its tree line, a link to
  Location). One bar for both pages: what's set here carries between them.

      <.bar at={@at} shift_min={@shift_min} lst={@lst} utc_offset_min={@utc_offset_min}
            site={@site} trees={@trees} horizon={@horizon} sun={@sun} />

  The page handles `"shift"` (`by`: minutes, or `"now"`). While a step is on
  its way the page's chart dims (LiveView's own loading class on `#sky`), so
  a tap answers at once even before the new sky arrives.
  """
  use Phoenix.Component

  alias Phoenix.LiveView.JS
  alias Controller.Sky.Daylight

  @w 144
  @h 40

  attr :at, :any, required: true, doc: "the time the sky is drawn for"
  attr :shift_min, :integer, required: true
  attr :lst, :any, required: true
  attr :utc_offset_min, :any, default: nil
  attr :site, :map, required: true, doc: "`lat`, `lon`, `set`"
  attr :trees, :boolean, default: false, doc: "whether a tree line is set"
  attr :horizon, :map, default: %{}, doc: "the tree line, degrees by direction"
  attr :sun, :map, required: true, doc: "`sun_info/3`"
  attr :loading, :string, default: "#sky", doc: "what dims while a step is on its way"

  def bar(assigns) do
    ~H"""
    <div class="sky-status">
      <div class="ss-time" role="group" aria-label="Time the sky is drawn for">
        <button type="button" class="ss-step" phx-click={JS.push("shift", value: %{by: "-60"}, loading: @loading)} aria-label="One hour earlier">−1 h</button>
        <div class="ss-clock" role="status" aria-live="polite">
          <strong>{clock(@at, @utc_offset_min)}<span :if={@shift_min != 0} class="ss-shift"> {shift_words(@shift_min)}</span></strong>
          <span>{date(@at, @utc_offset_min)} · sidereal {hm_deg(@lst)}</span>
        </div>
        <button type="button" class="ss-step" phx-click={JS.push("shift", value: %{by: "60"}, loading: @loading)} aria-label="One hour later">+1 h</button>
        <button type="button" class="ss-step ss-now" phx-click={JS.push("shift", value: %{by: "now"}, loading: @loading)} disabled={@shift_min == 0} aria-label="Back to now">Now</button>
      </div>

      <div class={["ss-sun", "ss-#{@sun.key}"]} role="img" aria-label={"#{@sun.name}. #{@sun.next}"}>
        <%!-- the solar graph, drawn in line on the toolbar's own ground: no box, every tone a token --%>
        <svg viewBox={"0 0 #{w()} #{h()}"} width={w()} height={h()} aria-hidden="true">
          <%!-- daylight: under the Sun's path while it is above the horizon --%>
          <polygon :for={points <- @sun.day} points={points} class="sg-day" />
          <%!-- twilight: a step under the horizon for as long as the Sun is in it, at dusk and at dawn; the gap between them is the dark --%>
          <rect :for={t <- @sun.twilight} x={t.x} y={y(0)} width={t.width} height={twilight_depth()} class="sg-twilight" />
          <line x1="0" y1={y(0)} x2={w()} y2={y(0)} class="sg-horizon" />
          <polyline :for={{side, points} <- @sun.runs} points={points} class={["sg-curve", "sg-#{side}"]} />
          <%!-- the time shown: a dot on the path, with the ground's tone around it so it stands off the line --%>
          <circle cx={@sun.x} cy={@sun.y} r="6" class="sg-halo" />
          <circle cx={@sun.x} cy={@sun.y} r="4" class="sg-sun" />
        </svg>
        <span class="ss-words"><strong>{@sun.name}</strong><span>{@sun.next}</span></span>
      </div>

      <.link navigate="/location" class={["ss-place", !@site.set && "tone-caution"]}>
        <strong>{if @site.set, do: latlon(@site), else: "Location not set"}</strong>
        <span>{if @site.set, do: trees_words(@trees, @horizon), else: "Drawn for 0° N, 0° E"}</span>
      </.link>
    </div>
    """
  end

  @doc """
  What the bar draws for the Sun: the phase at `at` and when it next
  changes, and the solar graph (the Sun's altitude noon to noon, a dot at
  `at`). Worked out once per sky, not per render.

  The path comes in `runs`, `{:up | :down, points}`, cut where the Sun
  crosses the horizon, so it is drawn bright while the Sun is up and dim
  while it is down; `day` is each run above the horizon closed along it,
  the daylight to fill; `twilight` is each stretch the Sun spends between
  the horizon and where the sky is dark, `%{x, width}` across the graph.
  """
  def sun_info(at, site, utc_offset_min) do
    alt = Daylight.sun_alt(at, site)
    {key, name} = Daylight.phase(alt)
    {start, samples} = Daylight.day(at, site, utc_offset_min)
    minutes = DateTime.diff(at, start) / 60
    runs = runs(samples, 0.0)

    %{
      key: key,
      name: name,
      alt: alt,
      next: next_words(key, Daylight.next_change(at, site), utc_offset_min),
      runs: for({side, run} <- runs, do: {side, points(run)}),
      day: for({:up, run} <- runs, do: points([{elem(hd(run), 0), 0.0}] ++ run ++ [{elem(List.last(run), 0), 0.0}])),
      twilight:
        for {:down, night} <- runs, {:up, run} <- runs(night, dark_below()) do
          {from, to} = {x(elem(hd(run), 0)), x(elem(List.last(run), 0))}
          %{x: from, width: Float.round(to - from, 1)}
        end,
      x: x(minutes),
      y: y(alt)
    }
  end

  # Samples (`{minutes, altitude}`) cut where the Sun crosses `level` (0: the horizon): the runs
  # above it (`:up`) and at or below it (`:down`), in order, each ending on the level itself (the
  # crossing, found between the two samples either side of it).
  defp runs([first | rest], level) do
    {done, run, _} =
      Enum.reduce(rest, {[], [first], first}, fn {m, a} = sample, {done, run, {m0, a0}} ->
        if side(a, level) == side(a0, level) do
          {done, [sample | run], sample}
        else
          cross = {m0 + (level - a0) / (a - a0) * (m - m0), level}
          {[{side(a0, level), Enum.reverse([cross | run])} | done], [sample, cross], sample}
        end
      end)

    {_, last} = hd(run)
    Enum.reverse([{side(last, level), Enum.reverse(run)} | done])
  end

  defp side(alt, level), do: if(alt > level, do: :up, else: :down)

  defp points(run), do: Enum.map_join(run, " ", fn {m, a} -> "#{x(m)},#{y(a)}" end)

  defp next_words(_, nil, _), do: "No change today"
  defp next_words(_, {t, {:day, _}}, off), do: "Sunrise #{clock(t, off)}"
  defp next_words(:day, {t, _}, off), do: "Sunset #{clock(t, off)}"
  defp next_words(_, {t, {:dark, _}}, off), do: "Dark from #{clock(t, off)}"
  defp next_words(_, {t, {_, name}}, off), do: "#{name} at #{clock(t, off)}"

  # the graph: a day across, the Sun's altitude up, squeezed so ±70° fits
  defp w, do: @w
  defp h, do: @h
  defp x(minutes), do: Float.round(minutes / (24 * 60) * @w * 1.0, 1)
  defp y(alt), do: Float.round(@h / 2 - alt * 0.26, 1)

  # twilight ends where Daylight says the sky is dark (the Sun 18° down), and on the graph reaches that far under the horizon
  defp dark_below do
    {_, _, below} = List.keyfind(Daylight.phases(), :astronomical, 0)
    below
  end

  defp twilight_depth, do: Float.round(y(dark_below()) - y(0), 1)

  defp clock(t, nil), do: Calendar.strftime(t, "%H:%M") <> " UTC"
  defp clock(t, off), do: Calendar.strftime(DateTime.add(t, off * 60, :second), "%H:%M")

  defp date(t, off), do: Calendar.strftime(DateTime.add(t, (off || 0) * 60, :second), "%a %b %-d")

  defp shift_words(min) when min > 0, do: "+#{div(min, 60)} h"
  defp shift_words(min), do: "−#{div(-min, 60)} h"

  defp hm_deg(deg) do
    h = deg / 15
    "#{trunc(h)}h#{String.pad_leading(to_string(trunc((h - trunc(h)) * 60)), 2, "0")}m"
  end

  # 37.77° N 122.42° W: a kilometre, enough to tell the sky is yours
  defp latlon(%{lat: lat, lon: lon}),
    do: "#{:erlang.float_to_binary(abs(lat) * 1.0, decimals: 2)}° #{if lat >= 0, do: "N", else: "S"} #{:erlang.float_to_binary(abs(lon) * 1.0, decimals: 2)}° #{if lon >= 0, do: "E", else: "W"}"

  # the tree line in a few words: its range, low to high, by direction
  defp trees_words(false, _), do: "No tree line set"

  defp trees_words(true, horizon) do
    values = horizon |> Map.values() |> Enum.filter(&is_number/1)

    case {Enum.min(values, fn -> 0 end), Enum.max(values, fn -> 0 end)} do
      {0, 0} -> "Clear to the horizon"
      {lo, hi} when lo == hi -> "Trees to #{round(hi)}°"
      {lo, hi} -> "Trees #{round(lo)}–#{round(hi)}°"
    end
  end
end
