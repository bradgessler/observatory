defmodule Controller.Components.SkyChart do
  @moduledoc """
  Sky charts, as layers: a `Controller.Sky.Scene` drawn as SVG in whichever
  projection the scene was built for (the dome, the horizon, the mount's
  axes). Each layer is a component, and each chart is a composition of them,
  so the Sky Map, the Scope page's live sky and an object's night
  (`Controller.Components.NightPath`) draw the frame, the grid, the trees and
  a path the same way:

    * `frame/1`: the svg itself, the sky's ground (a dome or a flat field)
      and the clip; layers go inside, words in its `:over` slot;
    * `grid/1`: altitude or hour lines, the horizon, the equator, the ecliptic;
    * `sky/1`: the constellation figures, the stars (sized by brightness),
      the planets, Moon and deep-sky objects;
    * `trees/1`: what's behind the tree line, shaded, and its edge;
    * `path/1`: one object's night (`Scene.night_path/4`): solid in the dark,
      dashed in twilight, dotted in daylight, a dot each hour, a ring at now;
    * `telescope/1`: the telescope's crosshair and its margin ring;
    * `grid_labels/1`: the compass and the grid's numbers.

  `chart/1` is the Sky Map's composition: all of them. With `interactive`,
  objects are tappable (`phx-click="pick"`, a tap on the sky `"clear"`) and
  the chart pinch-zoomable (the `SkyZoom` hook).

      <.chart id="skymap" scene={@scene} target={@target} path={@path} scope={@scope} ring={@ring} interactive />
  """
  use Phoenix.Component

  # stars this bright or brighter are each tappable; fainter ones are only drawn
  @tap_mag 4.0

  # -- the Sky Map's chart ---------------------------------------------------------------

  attr :id, :string, required: true
  attr :scene, :map, required: true
  attr :target, :map, default: nil, doc: "the picked object (`id`, `ra_deg`, `dec_deg`)"
  attr :path, :map, default: nil, doc: "the picked object's night (`Scene.night_path/4`)"
  attr :scope, :map, default: nil, doc: "where the telescope points: `%{x, y}` on this chart"
  attr :ring, :list, default: [], doc: "the telescope's margin, chart point lists"
  attr :interactive, :boolean, default: false
  attr :label, :string, default: "the sky"
  attr :class, :any, default: nil
  attr :rest, :global

  def chart(assigns) do
    ~H"""
    <.frame
      id={@id}
      scene={@scene}
      label={@label}
      class={@class}
      phx-hook={@interactive && "SkyZoom"}
      phx-click={@interactive && "clear"}
      {@rest}
    >
      <.grid scene={@scene} />
      <.sky scene={@scene} target={@target} interactive={@interactive} />
      <.trees scene={@scene} />
      <.path :if={@path} path={@path} />
      <.telescope scope={@scope} ring={@ring} />
      <:over><.grid_labels scene={@scene} /></:over>
    </.frame>
    """
  end

  # -- the layers ------------------------------------------------------------------------

  @doc "The svg, the sky's ground and its clip. Layers go inside (clipped to the sky); `:over` is drawn on top, unclipped."
  attr :id, :string, required: true
  attr :scene, :map, required: true
  attr :label, :string, required: true
  attr :class, :any, default: nil
  attr :rest, :global, include: ~w(phx-hook phx-click)
  slot :inner_block
  slot :over

  def frame(assigns) do
    assigns = assign(assigns, f: assigns.scene.frame, view: assigns.scene.view, clip: "#{assigns.id}-clip")

    ~H"""
    <svg id={@id} viewBox={@f.view_box} data-base={@f.view_box} class={["map", "map-#{@view}", "sky-#{@scene[:phase] || :dark}", @class]} role="img" aria-label={@label} {@rest}>
      <defs>
        <radialGradient id={"#{@id}-dome"} cx="50%" cy="50%" r="50%">
          <stop offset="70%" stop-color="var(--sky1)" /><stop offset="100%" stop-color="var(--sky2)" />
        </radialGradient>
        <linearGradient id={"#{@id}-air"} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--sky2)" /><stop offset="100%" stop-color="var(--sky1)" />
        </linearGradient>
        <clipPath id={@clip}>
          <circle :if={@view == :dome} r="100" />
          <rect :if={@view == :horizon} x="-180" y={@f.top} width="360" height={-@f.top} />
          <rect :if={@view == :mount} x="-180" y={@f.top} width="360" height={@f.bottom - @f.top} />
        </clipPath>
      </defs>

      <%!-- the sky itself: a dome, or a flat field --%>
      <circle :if={@view == :dome} r="100" fill={"url(##{@id}-dome)"} class="sky-edge" />
      <rect :if={@view == :horizon} x="-180" y={@f.top} width="360" height={-@f.top} fill={"url(##{@id}-air)"} class="sky-edge" />
      <rect :if={@view == :mount} x="-180" y={@f.top} width="360" height={@f.bottom - @f.top} fill="var(--sky1)" class="sky-edge" />

      <g clip-path={"url(##{@clip})"}>{render_slot(@inner_block)}</g>
      {render_slot(@over)}
    </svg>
    """
  end

  attr :scene, :map, required: true
  attr :except, :list, default: [], doc: "line classes to leave out (`\"equator\"`, `\"ecliptic\"`)"

  def grid(assigns) do
    assigns = assign(assigns, lines: Enum.reject(assigns.scene.grid.lines, &(to_string(&1.class) in assigns.except)))

    ~H"""
    <polygon :for={f <- @scene.grid.fills} points={f.points} class={["grid-fill", f.class]} pointer-events="none" />
    <polyline :for={l <- @lines} points={l.points} class={["grid", l.class]} pointer-events="none" />
    """
  end

  attr :scene, :map, required: true
  attr :target, :map, default: nil
  attr :interactive, :boolean, default: false

  def sky(assigns) do
    # the bright stars are each a thing to tap; the faint ones (most of them) are drawn as a few
    # dots in one path, so a step of the time sends a few kilobytes, not a hundred
    {bright, faint} = Enum.split_with(assigns.scene.stars, &(&1.mag <= @tap_mag or (assigns.target && assigns.target.id == &1.id)))
    {behind, clear} = Enum.split_with(faint, & &1.hidden)
    assigns = assign(assigns, bright: bright, faint_clear: dots(clear), faint_behind: dots(behind))

    ~H"""
    <polyline :for={l <- @scene.lines} points={l} class="lines" pointer-events="none" />

    <path :if={@faint_clear != ""} d={@faint_clear} class="stars-faint" pointer-events="none" />
    <path :if={@faint_behind != ""} d={@faint_behind} class="stars-faint hidden" pointer-events="none" />

    <g
      :for={o <- @bright}
      phx-click={@interactive && "pick"}
      phx-value-id={o.id}
      class={["obj", "star", o.mag > 3.5 && "faint", o.hidden && "hidden", @target && @target.id == o.id && "picked"]}
    >
      <circle :if={@interactive} class="hit" cx={r1(o.x)} cy={r1(o.y)} r={radius(o) + 3.5} />
      <circle cx={r1(o.x)} cy={r1(o.y)} r={radius(o)} />
      <text :if={o.proper && o.mag < 1.9} x={r1(o.x + 2.2)} y={r1(o.y + 1)}>{o.proper}</text>
    </g>

    <g
      :for={o <- @scene.dsos}
      phx-click={@interactive && "pick"}
      phx-value-id={o.id}
      class={["obj", o.kind, o.hidden && "hidden", @target && @target.id == o.id && "picked"]}
    >
      <circle :if={@interactive} class="hit" cx={r1(o.x)} cy={r1(o.y)} r="4.5" />
      <rect x={r1(o.x - 1.5)} y={r1(o.y - 1.5)} width="3" height="3" transform={"rotate(45 #{r1(o.x)} #{r1(o.y)})"} />
      <text :if={String.starts_with?(o.id, "sol-") or (o.mag < 6.5 and String.starts_with?(o.id, "m"))} x={r1(o.x + 2.6)} y={r1(o.y + 1)}>{short(o.name)}</text>
    </g>

    <%!-- the Sun, when it's up: nothing else is worth looking for near it, and it washes out the rest --%>
    <g :if={@scene[:sun]} class="sun" transform={"translate(#{r1(@scene.sun.x)} #{r1(@scene.sun.y)})"} pointer-events="none">
      <circle r="10" class="sun-glow" />
      <circle r="3.6" class="sun-disk" />
      <text x="5.5" y="1.4">Sun</text>
    </g>
    """
  end

  # dots as one path: a zero-length stroke with round caps at each point
  defp dots(stars), do: Enum.map_join(stars, "", &"M#{r1(&1.x)} #{r1(&1.y)}h0")

  attr :scene, :map, required: true

  def trees(assigns) do
    ~H"""
    <path :if={@scene.tree_fill} d={@scene.tree_fill} fill-rule="evenodd" class="treeline" pointer-events="none" />
    <polyline :for={l <- @scene.tree_line} points={l} class="treeline-edge" pointer-events="none" />
    """
  end

  @doc "One object's night: its path by how dark the sky is, a dot at each hour, a ring where it is now."
  attr :path, :map, required: true, doc: "`Scene.night_path/4`"

  def path(assigns) do
    ~H"""
    <polyline :for={s <- @path.segments} points={s.points} class={["path", s.class, s[:behind] && "behind"]} pointer-events="none" />
    <circle :for={h <- @path.hours} cx={r1(h.x)} cy={r1(h.y)} r="1.4" class={["hour", h.class, h[:behind] && "behind"]} pointer-events="none" />
    <circle :if={@path.now} cx={r1(@path.now.x)} cy={r1(@path.now.y)} r="4.5" class="mark" pointer-events="none" />
    """
  end

  attr :scope, :map, default: nil
  attr :ring, :list, default: []

  def telescope(assigns) do
    ~H"""
    <polyline :for={r <- @ring} points={r} class="aim" pointer-events="none" />
    <g :if={@scope} class="scope" transform={"translate(#{r1(@scope.x)} #{r1(@scope.y)})"} pointer-events="none">
      <circle r="5" fill="none" />
      <line x1="-8" y1="0" x2="-3" y2="0" /><line x1="3" y1="0" x2="8" y2="0" />
      <line x1="0" y1="-8" x2="0" y2="-3" /><line x1="0" y1="3" x2="0" y2="8" />
    </g>
    """
  end

  attr :scene, :map, required: true

  def grid_labels(assigns) do
    ~H"""
    <text :for={t <- @scene.grid.labels} x={t.x} y={t.y} class={t.class} text-anchor={t.anchor} pointer-events="none">{t.text}</text>
    """
  end

  @doc """
  Where a chart point sits in its frame, as percentages from the left and
  the top: for words laid over a chart in HTML, which stay 12 px at any size.
  (Only on a chart that never zooms; the Sky Map's words stay in the svg, so
  they zoom with it.)
  """
  def pct(%{x: fx, y: fy, w: w, h: h}, x, y), do: {Float.round((x - fx) / w * 100, 2), Float.round((y - fy) / h * 100, 2)}

  defp radius(%{mag: m}), do: max(0.45, 2.4 - m * 0.45)
  defp short(name), do: name |> String.split(" ") |> List.first()
  defp r1(x), do: Float.round(x * 1.0, 1)
end
