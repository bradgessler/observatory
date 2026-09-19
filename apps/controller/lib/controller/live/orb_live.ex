defmodule Controller.OrbLive do
  @moduledoc """
  The orb: the celestial sphere as a 3-D gizmo, seen from where you stand.

  Three axes are drawn from what the mount *reports* — the polar (RA) axis
  tilted to your latitude, the declination axis square to it, and the tube —
  with a curved arrow and a rate on whichever axis is actually turning.
  Under it, one analog strip per axis and STOP. Eyepiece/tilt mode comes later.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Sky.{Astro, Joystick, Pointing}
  alias Controller.{Modes, Settings}

  @rescan_ms 3_000
  @stick_max 800.0
  # sidereal rate, arcsec per second
  @sidereal 15.041
  @deg :math.pi() / 180

  # the orb: sphere radius in viewBox units, and a fixed camera south-southeast
  # of the observer, 25° up, so the horizon, the pole and the meridian all read
  @r 96.0
  @cam_el 25.0
  @cam_az 150.0

  # -- lifecycle ----------------------------------------------------------------------

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
    end

    # Nested in the bench (live_render) there is no router: params is an atom
    # and the mount id rides in the session.
    params = if(is_map(params), do: params, else: %{}) |> Map.put_new("id", session["id"])

    {:ok,
     socket
     |> assign(
       nested: session["nested"] == true,
       night: Settings.get("night", false),
       notice: nil,
       mounts: %{},
       refs: %{},
       held: [],
       stick_rate: nil,
       modes: Modes.active()
     )
     |> assign(selected: params["id"])
     |> rescan()}
  end

  # no handle_params: this view is nested inside the bench (child views may not define it)

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, @rescan_ms)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    {:noreply, assign(socket, mounts: Map.put(socket.assigns.mounts, snap.id, snap))}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _key, _v}, socket), do: {:noreply, assign(socket, modes: Modes.active())}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})

    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id) do
      Mount.subscribe(ref)
    end

    mounts =
      for {id, ref} <- refs, into: %{} do
        {id, socket.assigns.mounts[id] || safe_snapshot(ref)}
      end

    socket = assign(socket, refs: refs, mounts: mounts)
    if socket.assigns.selected in Map.keys(refs), do: socket, else: assign(socket, selected: first_id(socket))
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Enum.sort() |> List.first()

  defp safe_snapshot(ref) do
    try do
      Mount.snapshot(ref)
    catch
      _, _ -> %{id: ref.id, node: ref.node, connected: false, axes: %{}, tracking: :off, homed: false}
    end
  end

  # -- events -------------------------------------------------------------------------

  # The strips: touch and pull. Each strip is one axis of the actual mount; speed
  # grows with distance on a log scale from 1× at the dead zone to 800× at the
  # rim. The hook re-sends while held, which keeps the mount's deadman fed;
  # letting go sends stick_end. Same behaviour as the keypad.
  @impl true
  def handle_event("stick", %{"x" => x, "y" => y, "mag" => mag} = params, socket)
      when is_number(x) and is_number(y) and is_number(mag) do
    mag = mag |> max(0.0) |> min(1.0)
    rate = :math.pow(@stick_max, mag) |> max(1.0)
    snap = current(socket)
    ctx = Pointing.context()

    vector =
      case params["axis"] do
        "ra" -> {x / 1, 0.0}
        "dec" -> {0.0, x / 1}
        _ -> {x / 1, y / 1}
      end

    rates = Joystick.compass_vector(snap, ctx, vector, rate)
    socket = Enum.reduce(rates, socket, fn {axis, r}, s -> run(s, &Mount.slew(&1, axis, r, hold: true)) end)
    {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)), stick_rate: round(rate))}
  end

  def handle_event("stick_end", _params, socket) do
    snap = current(socket)
    held = socket.assigns[:held] || [:ra, :dec]

    socket =
      Enum.reduce(held, socket, fn axis, s ->
        # Letting go of an RA nudge while tracking should go back to tracking, not stop.
        if axis == :ra and snap && snap.tracking != :off,
          do: run(s, &Mount.track(&1, snap.tracking)),
          else: run(s, &Mount.stop(&1, axis))
      end)

    {:noreply, assign(socket, held: [], stick_rate: nil)}
  end

  def handle_event("estop", _, socket), do: {:noreply, run(socket, &Mount.emergency_stop/1)}

  def handle_event("night", _, socket) do
    night = !socket.assigns.night
    Settings.put("night", night)
    {:noreply, assign(socket, night: night)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  # Stand somewhere else to look at the orb (to match where the webcam is).
  def handle_event("view", %{"az" => az}, socket) do
    case Float.parse(az) do
      {a, _} ->
        Controller.Settings.put("orb_view_az", a)
        {:noreply, assign(socket, view_az: a)}

      :error ->
        {:noreply, socket}
    end
  end

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> assign(socket, notice: nil)
            {:error, :limit} -> assign(socket, notice: "soft limit")
            {:error, :not_connected} -> assign(socket, notice: "mount not connected")
            {:error, other} -> assign(socket, notice: inspect(other))
          end
        catch
          :exit, _ -> assign(socket, notice: "mount unreachable")
        end
    end
  end

  defp current(socket), do: socket.assigns.mounts[socket.assigns.selected]

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    snap = current(%{assigns: assigns})
    live? = snap && snap.connected && is_map(snap.axes[:ra]) && is_map(snap.axes[:dec])
    assigns = assign(assigns, snap: snap, scene: if(live?, do: scene(snap, Pointing.context())))

    ~H"""
    <.page id="orb" night={@night} class={if @nested, do: "orb-page nested", else: "orb-page"}>
      <:header :if={!@nested}>
        <.back navigate={if @selected, do: ~p"/#{@selected}", else: ~p"/"} label="keypad" />
        <.title>{@selected || "no mount"} · orb</.title>
        <.actions>
          <.help href={~p"/docs/keypad"} />
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
        </.actions>
      </:header>

      <%= if @scene do %>
        <.card class="orb-card">
          <.orb scene={@scene} held={@held} />
          <div class="orb-legend">
            <div class={["orb-key", "ra", @scene.ra.running && "running", :ra in @held && "live"]}>
              <span class="orb-k">◯ RA · polar</span>
              <b>{fmt(@snap.axes.ra.degrees)}</b>
              <span class="orb-motion">{motion(@scene.ra)}</span>
            </div>
            <div class={["orb-key", "dec", @scene.dec.running && "running", :dec in @held && "live"]}>
              <span class="orb-k">■ Dec</span>
              <b>{fmt(@snap.axes.dec.degrees)}</b>
              <span class="orb-motion">{motion(@scene.dec)}</span>
            </div>
            <div class="orb-key scope">
              <span class="orb-k">⌖ scope</span>
              <b>alt {fmt0(@scene.scope.alt)}° · az {fmt0(@scene.scope.az)}°</b>
              <span class="orb-motion">{if @scene.radec, do: fmt_radec(@scene.radec), else: "unhomed"}</span>
            </div>
          </div>
        </.card>

        <section class="eq">
          <%!-- each strip wears its axis's colour: this one turns that one --%>
          <div class={["strip", "strip-ra", :ra in @held && "live"]} id="strip-ra" phx-hook="Stick" data-lock="x" data-axis="ra" role="application" aria-label="pull left or right to turn around the polar axis">
            <span class="strip-mid strip-only"><i class="strip-dot ra"></i>RA · polar axis<b>{if :ra in @held and @stick_rate, do: "#{@stick_rate}×", else: "pull to turn"}</b></span>
            <div class="knob knob-h" data-knob></div>
          </div>

          <div class={["strip", "strip-dec", :dec in @held && "live"]} id="strip-dec" phx-hook="Stick" data-lock="x" data-axis="dec" role="application" aria-label="pull left or right to turn around the declination axis">
            <span class="strip-mid strip-only"><i class="strip-dot dec"></i>Dec axis<b>{if :dec in @held and @stick_rate, do: "#{@stick_rate}×", else: "pull to turn"}</b></span>
            <div class="knob knob-h" data-knob></div>
          </div>
        </section>

        <button class="stop-bar" phx-click="estop">STOP</button>

        <%!-- where you're standing; pick the one that matches the camera or your own spot --%>
        <% view = Controller.Settings.get("orb_view_az", 150.0) / 1 %>
        <div class="seg seg-4" role="radiogroup" aria-label="view the orb from">
          <button :for={{lbl, az} <- [{"from S", 150.0}, {"from E", 60.0}, {"from N", 330.0}, {"from W", 240.0}]} class={["seg-opt", abs(view - az) < 1 && "on"]} phx-click="view" phx-value-az={az} role="radio" aria-checked={to_string(abs(view - az) < 1)}>{lbl}</button>
        </div>
        <a class="orb-later" aria-disabled="true">eyepiece mode: later</a>

        <Controller.Components.Modes.modes modes={@modes} id={@selected} />
      <% else %>
        <section class="empty">
          <p :if={@snap}>{@selected}: not connected<span :if={@snap[:error]}> — {inspect(@snap.error)}</span></p>
          <p :if={!@snap}>No mount found. Plug the EQDIR cable into this machine, or connect to a node that has one.</p>
        </section>
      <% end %>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end

  attr :scene, :map, required: true
  attr :held, :list, required: true

  defp orb(assigns) do
    ~H"""
    <svg viewBox="-120 -112 240 236" class="orb-svg" role="img" aria-label="the sky as a sphere with the mount's three axes">
      <defs>
        <marker id="orb-head-ra" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 L6 3 L0 6 z" class="head-ra" />
        </marker>
        <marker id="orb-head-dec" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 L6 3 L0 6 z" class="head-dec" />
        </marker>
      </defs>

      <%!-- the sphere: silhouette, horizon, meridian, celestial equator (back halves dashed) --%>
      <circle r={@scene.r} class="rim" />
      <path d={@scene.meridian.back} class="ring meridian back" />
      <path d={@scene.horizon.back} class="ring horizon back" />
      <path d={@scene.equator.back} class="ring equator back" />
      <path d={@scene.meridian.front} class="ring meridian" />
      <path d={@scene.horizon.front} class="ring horizon" />
      <path d={@scene.equator.front} class="ring equator" />
      <text :for={{lbl, {x, y}} <- @scene.marks} x={x} y={y} class="mark">{lbl}</text>

      <%!-- 1 · polar / RA axis: fixed, tilted to the latitude; a circle at the pole --%>
      <line x1="0" y1="0" x2={px(@scene.ra.tail)} y2={py(@scene.ra.tail)} class="ax ax-ra tail" />
      <line id="orb-ax-ra" x1="0" y1="0" x2={px(@scene.ra.head)} y2={py(@scene.ra.head)}
        class={["ax", "ax-ra", @scene.ra.running && "running", :ra in @held && "live"]} />
      <circle cx={px(@scene.ra.head)} cy={py(@scene.ra.head)} r="3.2" class="end-ra" />
      <text x={px(@scene.ra.head) + 6} y={py(@scene.ra.head) - 4} class="lbl lbl-ra">pole · {fmt0(@scene.lat)}°</text>
      <%!-- reported motion: a single arrowhead laps the axis in the direction it turns --%>
      <g :if={@scene.ra.spin}>
        <path id="orbit-ra" d={@scene.ra.spin} class="orbit orbit-ra" />
        <polygon :for={{dur, begin} <- orbit_heads(orbit_dur(@scene.ra.rate))} points="-3.2,-2.2 3.2,0 -3.2,2.2" class="orbit-head orbit-head-ra">
          <animateMotion dur={dur} begin={begin} repeatCount="indefinite" rotate="auto"><mpath href="#orbit-ra" /></animateMotion>
        </polygon>
      </g>

      <%!-- 2 · dec axis: square to the polar axis, turned with it; a square at its end --%>
      <line x1="0" y1="0" x2={px(@scene.dec.tail)} y2={py(@scene.dec.tail)} class="ax ax-dec tail" />
      <line id="orb-ax-dec" x1="0" y1="0" x2={px(@scene.dec.head)} y2={py(@scene.dec.head)}
        class={["ax", "ax-dec", @scene.dec.running && "running", :dec in @held && "live"]} />
      <rect x={px(@scene.dec.head) - 3} y={py(@scene.dec.head) - 3} width="6" height="6" class="end-dec" />
      <text x={px(@scene.dec.head) + 6} y={py(@scene.dec.head) + 3} class="lbl lbl-dec">dec</text>
      <g :if={@scene.dec.spin}>
        <path id="orbit-dec" d={@scene.dec.spin} class="orbit orbit-dec" />
        <polygon :for={{dur, begin} <- orbit_heads(orbit_dur(@scene.dec.rate))} points="-3.2,-2.2 3.2,0 -3.2,2.2" class="orbit-head orbit-head-dec">
          <animateMotion dur={dur} begin={begin} repeatCount="indefinite" rotate="auto"><mpath href="#orbit-dec" /></animateMotion>
        </polygon>
      </g>

      <%!-- 3 · the tube: a crosshair where it points --%>
      <line id="orb-ax-scope" x1="0" y1="0" x2={px(@scene.scope.pt)} y2={py(@scene.scope.pt)} class="ax ax-scope" />
      <g class="end-scope" transform={"translate(#{px(@scene.scope.pt)} #{py(@scene.scope.pt)})"}>
        <circle r="5" />
        <line x1="-8" y1="0" x2="-3" y2="0" /><line x1="3" y1="0" x2="8" y2="0" />
        <line x1="0" y1="-8" x2="0" y2="-3" /><line x1="0" y1="3" x2="0" y2="8" />
      </g>
      <text x={px(@scene.scope.pt) + 9} y={py(@scene.scope.pt) + 11} class="lbl lbl-scope">scope</text>

      <text :if={!@scene.radec} x="0" y={@scene.r + 16} class="note">unhomed — assuming home</text>
    </svg>
    """
  end

  # -- geometry -----------------------------------------------------------------------
  #
  # Horizon frame, right-handed: x east, y north, z up. The mount at home has the
  # tube on the pole and the dec axis horizontal (east–west). The dec axis turns
  # by −H about the pole (the sky turns westward); the tube tilts by d about the
  # dec axis, then follows it. With H = ra_axis·ha_sign and d = dec_axis·dec_sign
  # this reproduces `Pointing.scope_radec/2` on both sides of the pier.
  # The camera is orthographic, fixed south-southeast of the observer and 25° up.

  @doc false
  def scene(snap, ctx) do
    lat = ctx.site.lat
    p = ctx.pointing
    off = if snap.homed, do: ctx.offset, else: %{"ra" => 0.0, "dec" => 0.0}
    ra = snap.axes.ra
    dec = snap.axes.dec
    h = (ra.degrees - off["ra"]) * p.ha_sign
    d = (dec.degrees - off["dec"]) * p.dec_sign

    # The physical mount, not the ideal one: its latitude knob may not match the
    # site (30° on the bench indoors) and its "north" is wherever the tripod
    # points. Both are settings; defaults are the site latitude and true north.
    tilt = Controller.Settings.get("mount_tilt_deg", lat) / 1
    heading = Controller.Settings.get("mount_heading_deg", 0) / 1
    pole = {sin(heading) * cos(tilt), cos(heading) * cos(tilt), sin(tilt)}
    east = {cos(heading), -sin(heading), 0.0}
    dec_axis = rotate(east, pole, -h)
    scope_model = pole |> rotate(east, d) |> rotate(pole, -h)

    radec = Pointing.scope_radec(snap, ctx)

    scope =
      case radec do
        nil ->
          scope_model

        {ra_deg, dec_deg} ->
          {alt, az} = Astro.alt_az(ra_deg, dec_deg, lat, Astro.lst_deg(ctx.now, ctx.site.lon))
          from_alt_az(alt, az)
      end

    cam = camera()
    # the end of the polar axis that is above your horizon is the one to label
    pole_end = if lat >= 0, do: pole, else: neg(pole)

    ra_sense = -p.ha_sign * turn_sign(ra)
    dec_sense = p.dec_sign * turn_sign(dec)

    %{
      r: @r,
      lat: lat,
      radec: radec,
      horizon: ring({0.0, 0.0, 1.0}, cam),
      meridian: ring(east, cam),
      equator: ring(pole, cam),
      marks: marks(cam),
      ra: %{
        head: project(pole_end, cam),
        tail: project(neg(pole_end), cam),
        running: ra.running == true,
        glyph: glyph(pole, ra_sense, cam),
        rate: rate_x(ra),
        spin: if(ra.running, do: spin(pole_end, if(lat >= 0, do: ra_sense, else: -ra_sense), 0.68, 0.2, cam))
      },
      dec: %{
        head: project(scale(dec_axis, 0.6), cam),
        tail: project(scale(dec_axis, -0.6), cam),
        running: dec.running == true,
        glyph: glyph(dec_axis, dec_sense, cam),
        rate: rate_x(dec),
        spin: if(dec.running, do: spin(dec_axis, dec_sense, 0.42, 0.16, cam))
      },
      scope: %{pt: project(scope, cam), model: scope_model, vec: scope, alt: alt_of(scope), az: az_of(scope)}
    }
  end

  # Which way the axis is turning, as reported: the observed velocity when we
  # have one, else the driver's direction bit (forward = degrees increasing).
  defp turn_sign(ax) do
    v = ax[:deg_per_s] || 0.0

    cond do
      v > 1.0e-6 -> 1
      v < -1.0e-6 -> -1
      ax[:direction] == :reverse -> -1
      true -> 1
    end
  end

  defp rate_x(ax), do: abs(ax[:deg_per_s] || 0.0) * 3600 / @sidereal

  # A right-handed turn about an axis pointing away from the viewer reads clockwise.
  defp glyph(axis, sense, {f, _, _}), do: if((sense > 0) == (dot(axis, f) > 0), do: "↻", else: "↺")

  # Where you stand to look at the orb. A setting, so it can match the webcam.
  defp camera do
    e = @cam_el * @deg
    a = (Controller.Settings.get("orb_view_az", @cam_az) / 1) * @deg
    pos = {cos_r(e) * :math.sin(a), cos_r(e) * :math.cos(a), :math.sin(e)}
    f = neg(pos)
    r = normalize(cross(f, {0.0, 0.0, 1.0}))
    u = cross(r, f)
    {f, r, u}
  end

  # {x, y, depth}: screen x right, y down, depth > 0 is the far side of the sphere
  defp project(v, {f, r, u}), do: {@r * dot(v, r), -@r * dot(v, u), dot(v, f)}

  # numeric, rounded, so labels can be offset from them in the template
  defp px({x, _, _}), do: Float.round(x * 1.0, 1)
  defp py({_, y, _}), do: Float.round(y * 1.0, 1)

  # A great circle with the given normal, as front and back path strings.
  defp ring(normal, cam) do
    {u1, u2} = perps(normal)

    0..72
    |> Enum.map(fn i ->
      t = i * 5 * @deg
      project(add(scale(u1, :math.cos(t)), scale(u2, :math.sin(t))), cam)
    end)
    |> split()
  end

  defp split(pts) do
    {front, back} =
      pts
      |> Enum.chunk_every(2, 1, :discard)
      |> Enum.chunk_by(fn [{_, _, d1}, {_, _, d2}] -> d1 + d2 < 0 end)
      |> Enum.reduce({[], []}, fn [[{_, _, d1} = first, {_, _, d2}] | _] = chunk, {front, back} ->
        seg = "M" <> pt(first) <> Enum.map_join(chunk, "", fn [_, p2] -> "L" <> pt(p2) end)
        if d1 + d2 < 0, do: {[seg | front], back}, else: {front, [seg | back]}
      end)

    %{front: front |> Enum.reverse() |> Enum.join(" "), back: back |> Enum.reverse() |> Enum.join(" ")}
  end

  # A full circle around `axis`, turning in `sense` (+1 right-handed), placed `c`
  # of the way out along it with radius `rr`. The path runs the way the axis
  # turns, so an arrowhead animated along it shows the direction of rotation.
  defp spin(axis, sense, c, rr, cam) do
    {u1, u2} = perps(axis)
    centre = scale(axis, c)

    Enum.map_join(0..36, "", fn i ->
      t = i * 10 * @deg
      v = add(centre, add(scale(u1, rr * :math.cos(t)), scale(u2, sense * rr * :math.sin(t))))
      if(i == 0, do: "M", else: "L") <> pt(project(v, cam))
    end) <> "Z"
  end

  # One lap per `dur` seconds: faster axis, faster arrows, within reason.
  defp orbit_dur(rate_x) when rate_x <= 0, do: 4.0
  defp orbit_dur(rate_x), do: Float.round((6.0 / :math.pow(max(rate_x, 1.0), 0.45)) |> max(0.6) |> min(6.0), 2)

  # three arrowheads a third of a lap apart (a negative begin sets the phase)
  defp orbit_heads(dur), do: for(i <- 0..2, do: {"#{dur}s", "-#{Float.round(dur * i / 3, 2)}s"})

  defp marks(cam) do
    for {lbl, v, dx, dy} <- [
          {"N", {0.0, 1.0, 0.0}, 0, -3},
          {"S", {0.0, -1.0, 0.0}, 0, 9},
          {"E", {1.0, 0.0, 0.0}, 4, 3},
          {"W", {-1.0, 0.0, 0.0}, -10, 3},
          {"zenith", {0.0, 0.0, 1.0}, -14, -4}
        ] do
      {x, y, _} = project(v, cam)
      {lbl, {r1(x + dx), r1(y + dy)}}
    end
  end

  # two unit vectors square to `a` with u1 × u2 = a
  defp perps(a) do
    {_, _, z} = a
    seed = if abs(z) < 0.9, do: {0.0, 0.0, 1.0}, else: {1.0, 0.0, 0.0}
    u1 = normalize(cross(a, seed))
    {u1, cross(a, u1)}
  end

  # Rodrigues: rotate `v` about unit axis `k` by `deg` (right-handed)
  defp rotate({x, y, z} = v, {kx, ky, kz} = k, deg) do
    t = deg * @deg
    c = :math.cos(t)
    s = :math.sin(t)
    {cx, cy, cz} = cross(k, v)
    kd = (kx * x + ky * y + kz * z) * (1 - c)
    {x * c + cx * s + kx * kd, y * c + cy * s + ky * kd, z * c + cz * s + kz * kd}
  end

  defp from_alt_az(alt, az), do: {cos(alt) * sin(az), cos(alt) * cos(az), sin(alt)}
  defp alt_of({_, _, z}), do: :math.asin(max(-1.0, min(1.0, z))) / @deg
  defp az_of({x, y, _}), do: Astro.norm360(:math.atan2(x, y) / @deg)

  defp cross({ax, ay, az}, {bx, by, bz}), do: {ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx}
  defp dot({ax, ay, az}, {bx, by, bz}), do: ax * bx + ay * by + az * bz
  defp add({ax, ay, az}, {bx, by, bz}), do: {ax + bx, ay + by, az + bz}
  defp scale({x, y, z}, s), do: {x * s, y * s, z * s}
  defp neg(v), do: scale(v, -1.0)

  defp normalize(v) do
    n = :math.sqrt(dot(v, v))
    if n < 1.0e-9, do: v, else: scale(v, 1 / n)
  end

  defp cos(deg), do: :math.cos(deg * @deg)
  defp sin(deg), do: :math.sin(deg * @deg)
  defp cos_r(rad), do: :math.cos(rad)

  # -- text -----------------------------------------------------------------------------

  defp motion(%{running: false}), do: "still"
  defp motion(%{glyph: g, rate: r}) when r >= 0.5, do: "#{g} #{round(r)}×"
  defp motion(%{glyph: g}), do: "#{g} …"

  defp fmt(deg) when is_number(deg) do
    sign = if deg < 0, do: "−", else: "+"
    d = abs(deg)
    whole = trunc(d)
    min = (d - whole) * 60
    "#{sign}#{whole}° #{:erlang.float_to_binary(min * 1.0, decimals: 1)}′"
  end

  defp fmt(_), do: "—"

  defp fmt_radec({ra_deg, dec_deg}) do
    hours = ra_deg / 15
    h = trunc(hours)
    m = trunc((hours - h) * 60)
    sign = if dec_deg < 0, do: "−", else: "+"
    "RA #{h}h #{String.pad_leading(Integer.to_string(m), 2, "0")}m · Dec #{sign}#{fmt0(abs(dec_deg))}°"
  end

  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)
  defp r1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp pt({x, y, _}), do: r1(x) <> " " <> r1(y)
end
