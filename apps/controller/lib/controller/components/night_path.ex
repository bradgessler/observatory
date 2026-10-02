defmodule Controller.Components.NightPath do
  @moduledoc """
  One object's night, as a picture: where it goes across the sky from now
  to dawn, drawn by how dark the sky is at each stretch (solid in the dark,
  dashed in twilight, dotted in daylight), a dot at each hour and a ring
  where it is now. On an object's page and beside Tonight's list.

  It is the Sky Map's chart recomposed (`Controller.Components.SkyChart`'s
  layers: the same frame, grid, tree line and path, in the projection this
  viewer picked), with one difference: no stars. They wheel past through the
  night, so a backdrop of one moment would be wrong for every hour but the
  first; the horizon, the compass and the trees stay put, and those are what
  "where will it be" is measured against.

  Its words (the compass, the hours, Now) are HTML laid over the chart, so
  they stay 12 px however big it's drawn.

      <.figure id="m31-night" scene={@scene} obj={@obj} utc_offset_min={@utc_offset_min} />
  """
  use Phoenix.Component

  alias Controller.Components.SkyChart
  alias Controller.Sky.Scene

  @kinds [{"dark", "Dark"}, {"twilight", "Twilight"}, {"day", "Daylight"}]

  attr :id, :string, required: true
  attr :scene, :map, required: true, doc: "built for now (it may carry stars; they aren't drawn)"
  attr :obj, :map, required: true, doc: "`name`, `ra_deg`, `dec_deg`"
  attr :utc_offset_min, :any, default: nil
  attr :class, :any, default: nil

  def figure(assigns) do
    %{scene: scene, obj: obj} = assigns
    path = Scene.night_path(scene, obj.ra_deg, obj.dec_deg, assigns.utc_offset_min)
    f = scene.frame

    now = path.now && place(f, path.now.x, path.now.y)
    compass = Enum.map(scene.grid.labels, fn t -> t |> Map.merge(place(f, t.x, t.y)) |> Map.put(:class, prefixed(t.class)) end)

    assigns =
      assign(assigns,
        path: path,
        aspect: "#{f.w} / #{f.h}",
        compass: compass,
        now: now,
        # an hour's word gives way to Now and to the compass
        hours: thin(path.hours, f, if(now, do: [now | compass], else: compass)),
        kinds: for({k, words} <- @kinds, k in path.classes, do: {k, words})
      )

    ~H"""
    <figure class={["night-path", @class]}>
      <div class="np-chart" style={"aspect-ratio: #{@aspect}"}>
        <SkyChart.frame id={@id} scene={@scene} label={"#{@obj.name}'s path across the sky from now to dawn"}>
          <%!-- the equator and the ecliptic wheel with the stars: left out for the same reason --%>
          <SkyChart.grid scene={@scene} except={["equator", "ecliptic"]} />
          <SkyChart.trees scene={@scene} />
          <SkyChart.path path={@path} />
        </SkyChart.frame>
        <span :for={t <- @compass} class={["np-word", t.class, anchor(t.anchor)]} style={pos(t)} aria-hidden="true">{t.text}</span>
        <span :for={h <- @hours} class={["np-word", "np-hour", h.class, h.side]} style={pos(h)} aria-hidden="true">{h.label}</span>
        <span :if={@now} class={["np-word", "np-now", @now.side]} style={pos(@now)} aria-hidden="true">Now</span>
      </div>
      <ul :if={@kinds != []} class="np-keys" aria-hidden="true">
        <li :for={{k, words} <- @kinds}>
          <svg class="np-key" viewBox="0 0 28 6" width="28" height="6" aria-hidden="true"><line class={["path", k]} x1="3" y1="3" x2="25" y2="3" /></svg>
          {words}
        </li>
      </ul>
      <figcaption class="dim">{caption(@path)}</figcaption>
    </figure>
    """
  end

  defp caption(%{segments: []}), do: "It doesn't rise before dawn."
  defp caption(%{now: nil}), do: "Below the horizon now: its path from when it rises until dawn, a dot each hour."
  defp caption(_), do: "From now until dawn, a dot each hour."

  # a chart point as percentages, and which side of it its word goes (away from the nearer edge)
  defp place(f, x, y) do
    {left, top} = SkyChart.pct(f, x, y)
    %{left: left, top: top, side: if(left > 78, do: "left", else: "right")}
  end

  defp pos(%{left: l, top: t}), do: "left: #{l}%; top: #{t}%"

  # the grid's own classes ("tick", "card", "tick pole"), named apart from the page's components
  defp prefixed(class), do: class |> to_string() |> String.split() |> Enum.map_join(" ", &("np-" <> &1))

  defp anchor("middle"), do: "mid"
  defp anchor("end"), do: "end"
  defp anchor(_), do: "start"

  # the hours' words, thinned so none sits on another (or on Now): measured in
  # widths of the chart, a word needs about a tenth of it
  defp thin(hours, f, taken) do
    ratio = f.h / f.w

    hours
    |> Enum.reduce({taken, []}, fn h, {taken, kept} ->
      p = Map.merge(h, place(f, h.x, h.y))
      clear? = Enum.all?(taken, fn q -> abs(q.left - p.left) > 11 or abs(q.top - p.top) * ratio > 5 end)
      if clear?, do: {[p | taken], [p | kept]}, else: {taken, kept}
    end)
    |> elem(1)
    |> Enum.reverse()
  end
end
