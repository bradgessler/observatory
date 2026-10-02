defmodule Controller.Components.Scope do
  @moduledoc """
  The telescope as a picture, posed from the encoders, in 3-D: a tripod, the
  mount head turning on the polar axis, the Dec housing, the saddle and the
  tube on it (dew shield, rings, focuser and diagonal), the counterweight on
  its shaft opposite. An alt-az form (a fork on a base) for mounts that are
  not German equatorials.

  Rendered on the server by `Controller.Render3D` into shaded SVG polygons,
  from the 250 ms snapshot, like everything else on the page: no WebGL, no
  script. Nothing here reads the mount or the settings: everything arrives
  in a pose map, so the same component serves a page, a badge and (later) a
  rendered still.

      <.scope pose={Scope.pose_from(snap, ctx)} label="sim-eq · equatorial" />

  Conventions shared with the orb: an east-north-up frame (x east, y north,
  z up), Rodrigues rotations, the camera from the south-south-east, a little
  above, so the counterweight reads. Sizes are metres, roughly an EQ6-R
  with a 102 mm refractor.
  """
  use Phoenix.Component

  alias Controller.Render3D, as: R

  @deg :math.pi() / 180

  # the view: from the south-south-east, a little above, so the counterweight reads
  @cam_az 150.0
  @cam_el 18.0

  # metres: the tripod's top, the polar axis's pivot above it, the tube
  @hub_z 0.92
  @feet_r 0.5
  @tube_r 0.058
  @tube_front 0.36
  @tube_back 0.36

  attr :pose, :map, required: true
  attr :size, :integer, default: 240
  attr :label, :string, default: nil
  attr :detail, :boolean, default: true
  attr :class, :string, default: nil

  def scope(assigns) do
    {polys, overlays, shadow} = model(assigns.pose, assigns.detail)
    assigns = assign(assigns, polys: polys, overlays: overlays, shadow: shadow, words: words(assigns.pose, assigns.label))

    ~H"""
    <svg
      class={["scope-svg", "scope-3d", @class]}
      viewBox="-74 -62 148 126"
      width={@size}
      height={round(@size * 126 / 148)}
      role="img"
      aria-label={@words}
    >
      <ellipse :if={@shadow} cx={elem(@shadow, 0)} cy={elem(@shadow, 1)} rx={elem(@shadow, 2)} ry={elem(@shadow, 3)} class="sc-ground" />
      <%!-- far to near, each face shaded by how squarely it faces the light --%>
      <polygon :for={p <- @polys} class={"m-#{p.mat} l#{p.level}"} points={p.points} />
      <%= for part <- @overlays do %>
        <%= case part do %>
          <% {:disc, cx, cy, r, cls} -> %>
            <circle cx={cx} cy={cy} r={r} class={cls} />
          <% {:arc, d, cls} -> %>
            <path d={d} class={cls} fill="none" />
        <% end %>
      <% end %>
    </svg>
    """
  end

  @doc """
  A pose for an equatorial mount from a driver snapshot and a pointing context.

  The polar axis comes from the fitted model when the mount has been
  star-aligned, otherwise from the mount-as-it-stands settings (site latitude,
  due north), which is what the orb draws too.
  """
  def pose_from(snap, ctx, opts \\ [])

  def pose_from(%{axes: %{ra: ra, dec: dec}} = snap, ctx, opts) when is_map(ctx) do
    p = ctx.pointing
    off = if snap[:homed], do: ctx.offset, else: %{"ra" => 0.0, "dec" => 0.0}
    lat = ctx.site.lat

    {axis_alt, axis_az} =
      case opts[:model] || ctx[:model] do
        %{axis_alt: a, axis_az: z} -> {a, z}
        _ -> {Controller.Settings.get("mount_tilt_deg", lat) / 1, Controller.Settings.get("mount_heading_deg", 0) / 1}
      end

    %{
      kind: Map.get(snap, :kind, :equatorial),
      polar_alt: axis_alt,
      polar_az: axis_az,
      ha_deg: (ra.degrees - off["ra"]) * p.ha_sign,
      dec_deg: (dec.degrees - off["dec"]) * p.dec_sign,
      running: %{ra: ra.running, dec: dec.running},
      tracking: tracking_of(snap, opts[:tracker])
    }
  end

  def pose_from(_, _, _), do: nil

  defp tracking_of(_snap, %{}), do: :model
  defp tracking_of(%{tracking: mode}, _) when mode != :off, do: :sidereal
  defp tracking_of(_, _), do: :off

  # -- the model ------------------------------------------------------------------------

  # {polygons far to near, overlays (motion arcs, the tracking lamp), the ground shadow}
  defp model(pose, detail?) do
    cam = camera()
    n = if detail?, do: 16, else: 10
    {faces, pivots} = if pose[:kind] == :altaz, do: altaz(pose, n, detail?), else: equatorial(pose, n, detail?)
    polys = R.render(faces, cam)
    {polys, overlays(pose, pivots, cam), shadow(cam)}
  end

  defp equatorial(pose, n, detail?) do
    pole = from_alt_az(pose[:polar_alt] || 38.0, pose[:polar_az] || 0.0)
    east = R.normalize(R.cross({0.0, 0.0, 1.0}, pole)) |> fallback({1.0, 0.0, 0.0})
    h = pose[:ha_deg] || 0.0
    d = pose[:dec_deg] || 0.0

    hub = {0.0, 0.0, @hub_z}
    base = R.add(hub, {0.0, 0.0, 0.07})
    # the pivot where the polar and Dec axes cross
    pivot = R.add(base, R.add(R.scale(pole, 0.1), {0.0, 0.0, 0.05}))
    dec = R.rotate(east, pole, -h)
    tube = R.rotate(pole, dec, d)
    saddle = R.add(pivot, R.scale(dec, 0.19))
    centre = R.add(saddle, R.scale(dec, 0.016 + @tube_r))
    # "up" on the tube: square to it and to the Dec axis, where the focuser's diagonal points
    up = R.normalize(R.cross(tube, dec))

    faces =
      tripod(hub, n, detail?) ++
        [
          # the azimuth base and the latitude block it carries
          R.cylinder(hub, base, 0.085, :metal, sides: n),
          R.box(R.add(base, R.scale(pole, 0.02)), pole, east, {0.12, 0.1, 0.07}, :metal),
          # the polar housing, along the polar axis, with the RA motor box on it
          R.cylinder(R.sub(pivot, R.scale(pole, 0.17)), R.add(pivot, R.scale(pole, 0.05)), 0.066, :metal, sides: n),
          R.box(R.add(R.sub(pivot, R.scale(pole, 0.08)), R.scale(R.normalize(R.cross(pole, east)), -0.07)), pole, east, {0.1, 0.07, 0.06}, :dark),
          # the Dec housing out to the saddle, and the counterweight shaft the other way
          R.cylinder(R.sub(pivot, R.scale(dec, 0.04)), R.add(pivot, R.scale(dec, 0.17)), 0.056, :metal, sides: n),
          R.cylinder(R.sub(pivot, R.scale(dec, 0.04)), R.sub(pivot, R.scale(dec, 0.44)), 0.012, :steel, sides: 8),
          R.cylinder(R.sub(pivot, R.scale(dec, 0.31)), R.sub(pivot, R.scale(dec, 0.39)), 0.072, :dark, sides: n),
          # the saddle plate, along the tube
          R.box(R.add(saddle, R.scale(dec, 0.008)), tube, up, {0.2, 0.06, 0.016}, :dark)
        ] ++ ota(centre, tube, up, n, detail?)

    {List.flatten(faces), %{ra: {pivot, pole}, dec: {saddle, dec}, lamp: base, tube: {centre, tube}}}
  end

  # the optical tube: white, a dew shield at the front, the lens dark inside, rings, and at the back the focuser and a diagonal
  defp ota(c, tube, up, n, detail?) do
    front = R.add(c, R.scale(tube, @tube_front))
    back = R.sub(c, R.scale(tube, @tube_back))
    shield = R.sub(front, R.scale(tube, 0.17))

    [
      R.cylinder(back, shield, @tube_r, :tube, sides: n),
      R.cylinder(shield, front, @tube_r + 0.008, :tube, sides: n, cap_b: :lens),
      if(detail?, do: [R.cylinder(R.sub(c, R.scale(tube, 0.13)), R.sub(c, R.scale(tube, 0.1)), @tube_r + 0.007, :dark, sides: n), R.cylinder(R.add(c, R.scale(tube, 0.1)), R.add(c, R.scale(tube, 0.13)), @tube_r + 0.007, :dark, sides: n)], else: []),
      R.cylinder(back, R.sub(back, R.scale(tube, 0.08)), 0.03, :metal, sides: 10),
      if(detail?,
        do: [
          R.box(R.sub(back, R.scale(tube, 0.11)), tube, up, {0.05, 0.05, 0.05}, :dark),
          R.cylinder(R.add(R.sub(back, R.scale(tube, 0.11)), R.scale(up, 0.025)), R.add(R.sub(back, R.scale(tube, 0.11)), R.scale(up, 0.09)), 0.016, :steel, sides: 8)
        ],
        else: []
      )
    ]
  end

  # three legs from the hub out to the feet, and a tray between them
  defp tripod(hub, n, detail?) do
    legs =
      for a <- [20.0, 140.0, 260.0] do
        top = R.add(hub, {0.06 * sin(a), 0.06 * cos(a), -0.02})
        foot = {@feet_r * sin(a), @feet_r * cos(a), 0.0}
        R.cylinder(top, foot, 0.016, :leg, sides: 6)
      end

    head = R.cylinder(R.sub(hub, {0.0, 0.0, 0.05}), hub, 0.1, :dark, sides: n)
    tray = if detail?, do: [R.cylinder({0.0, 0.0, 0.38}, {0.0, 0.0, 0.4}, 0.2, :dark, sides: 3)], else: []
    [legs, head, tray]
  end

  defp altaz(pose, n, detail?) do
    az = pose[:az_deg] || 0.0
    alt = pose[:alt_deg] || 0.0
    hub = {0.0, 0.0, @hub_z}
    base = R.add(hub, {0.0, 0.0, 0.08})
    across = {cos(az), -sin(az), 0.0}
    pivot = R.add(base, {0.0, 0.0, 0.26})
    tube = from_alt_az(alt, az)
    arm = R.add(pivot, R.scale(across, 0.1))
    up = R.normalize(R.cross(tube, across))

    faces =
      tripod(hub, n, detail?) ++
        [
          R.cylinder(hub, base, 0.12, :metal, sides: n),
          R.box(R.add(R.add(base, R.scale(across, 0.1)), {0.0, 0.0, 0.13}), {0.0, 0.0, 1.0}, R.cross(across, {0.0, 0.0, 1.0}) |> R.scale(-1.0), {0.26, 0.08, 0.04}, :metal),
          R.cylinder(arm, R.add(arm, R.scale(across, -0.04)), 0.05, :dark, sides: n)
        ] ++ ota(R.add(pivot, R.scale(across, -0.02)), tube, up, n, detail?)

    {List.flatten(faces), %{ra: {base, {0.0, 0.0, 1.0}}, dec: {pivot, across}, lamp: base, tube: {R.add(pivot, R.scale(across, -0.02)), tube}}}
  end

  @doc false
  # The model's axes on the screen, `%{tube: {from, to}, polar: {from, to}}` in
  # screen units: what the pose put where, for a test to check without reading
  # polygons.
  def skeleton(pose) do
    cam = camera()
    {_faces, pivots} = if pose[:kind] == :altaz, do: altaz(pose, 6, false), else: equatorial(pose, 6, false)
    ends = fn {c, dir}, len -> {xy(R.project(R.sub(c, R.scale(dir, len)), cam)), xy(R.project(R.add(c, R.scale(dir, len)), cam))} end
    %{tube: ends.(pivots.tube, @tube_back), polar: ends.(pivots.ra, 0.15)}
  end

  defp xy({x, y, _}), do: {x, y}

  defp camera, do: R.camera({0.0, 0.0, @hub_z + 0.12}, az: @cam_az, el: @cam_el, distance: 4.2, focal: 380.0)

  # the shadow on the ground under the tripod, an ellipse in perspective
  defp shadow(cam) do
    {x, y, _} = R.project({0.0, 0.0, 0.0}, cam)
    {xe, _, _} = R.project({@feet_r * 1.1 * :math.cos(@cam_az * @deg), -@feet_r * 1.1 * :math.sin(@cam_az * @deg), 0.0}, cam)
    rx = abs(xe - x)
    {r1(x), r1(y), r1(rx), r1(rx * :math.sin(@cam_el * @deg))}
  end

  # motion arcs round an axis while it turns, and the tracking lamp
  defp overlays(pose, pivots, cam) do
    running = pose[:running] || %{}
    {ra_c, ra_axis} = pivots.ra
    {dec_c, dec_axis} = pivots.dec
    ra_key = if pose[:kind] == :altaz, do: :az, else: :ra
    dec_key = if pose[:kind] == :altaz, do: :alt, else: :dec

    List.flatten([
      arc_of(ra_c, ra_axis, 0.16, "sc-spin-ra", running[ra_key], cam),
      arc_of(dec_c, dec_axis, 0.12, "sc-spin-dec", running[dec_key], cam),
      lamp(pose, pivots.lamp, cam)
    ])
  end

  defp arc_of(_centre, _axis, _r, _cls, running, _cam) when running != true, do: []

  defp arc_of(centre, axis, r, cls, _running, cam) do
    {u1, u2} = R.perps(axis)

    d =
      for(i <- 0..12, do: (i * 12 - 72) * @deg)
      |> Enum.map(fn t -> R.project(R.add(centre, R.scale(R.add(R.scale(u1, :math.cos(t)), R.scale(u2, :math.sin(t))), r)), cam) end)
      |> Enum.with_index()
      |> Enum.map_join(" ", fn {{x, y, _}, i} -> "#{if i == 0, do: "M", else: "L"}#{r1(x)},#{r1(y)}" end)

    [{:arc, d, cls}]
  end

  defp lamp(%{tracking: t}, at, cam) when t in [:sidereal, :model] do
    {x, y, _} = R.project(at, cam)
    [{:disc, r1(x), r1(y), 4.0, "sc-lamp"}]
  end

  defp lamp(_, _, _), do: []

  # -- words ----------------------------------------------------------------------------

  defp words(pose, label) do
    kind = if pose[:kind] == :altaz, do: "alt-az mount", else: "equatorial mount"

    numbers =
      if pose[:kind] == :altaz,
        do: "azimuth #{fmt(pose[:az_deg])}°, altitude #{fmt(pose[:alt_deg])}°",
        else: "RA #{fmt(pose[:ha_deg])}°, Dec #{fmt(pose[:dec_deg])}°"

    state =
      cond do
        pose[:tracking] in [:sidereal, :model] -> "tracking"
        Enum.any?(pose[:running] || %{}, fn {_, v} -> v end) -> "moving"
        true -> "still"
      end

    [label, kind, numbers, state] |> Enum.reject(&is_nil/1) |> Enum.join(" · ")
  end

  defp fmt(nil), do: "0"
  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 0)
  defp fmt(_), do: "0"

  # -- vectors --------------------------------------------------------------------------

  defp from_alt_az(alt, az), do: {cos(alt) * sin(az), cos(alt) * cos(az), sin(alt)}

  defp fallback({x, y, z} = v, alt) do
    if :math.sqrt(x * x + y * y + z * z) < 1.0e-6, do: alt, else: v
  end

  defp cos(deg), do: :math.cos(deg * @deg)
  defp sin(deg), do: :math.sin(deg * @deg)
  defp r1(x), do: Float.round(x * 1.0, 1)
end
