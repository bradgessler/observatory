defmodule Controller.Components.Scope do
  @moduledoc """
  The telescope as a picture, posed from the encoders: tripod, pier, the head
  turning on the polar axis, the tube swinging on the Dec axis, the
  counterweight opposite. An alt-az form (a fork on a base) for mounts that
  are not German equatorials.

  Server-rendered SVG from the 250 ms snapshot, like the orb; the difference
  is that the orb draws the geometry and this draws the thing. Nothing here
  reads the mount or the settings: everything arrives in a pose map, so the
  same component serves a page, a badge and (later) a rendered still.

      <.scope pose={Scope.pose_from(snap, ctx)} label="sim-eq · equatorial" />

  Conventions shared with the orb: an east-north-up frame (x east, y north,
  z up), Rodrigues rotations, an orthographic camera from the south-east.
  """
  use Phoenix.Component

  @deg :math.pi() / 180

  # the view: from the south-south-east, a little above, so the counterweight reads
  @cam_az 150.0
  @cam_el 20.0

  # Proportions, in units of the model's half-height. Chosen so the widest
  # pose (the tube across the view) still fits the frame with a margin.
  @pier_top 0.62
  @ground_r 0.42
  @head 0.22
  @saddle 0.26
  @cw 0.42
  @tube 0.40
  @scale 86.0

  attr :pose, :map, required: true
  attr :size, :integer, default: 240
  attr :label, :string, default: nil
  attr :detail, :boolean, default: true
  attr :class, :string, default: nil

  def scope(assigns) do
    assigns = assign(assigns, parts: parts(assigns.pose, assigns.detail), words: words(assigns.pose, assigns.label))

    ~H"""
    <svg
      class={["scope-svg", @class]}
      viewBox="-74 -62 148 126"
      width={@size}
      height={round(@size * 126 / 148)}
      role="img"
      aria-label={@words}
    >
      <%!-- painter's order: whatever is further from the camera is drawn first --%>
      <%= for part <- @parts do %>
        <%= case part do %>
          <% {:line, x1, y1, x2, y2, cls, w} -> %>
            <line x1={x1} y1={y1} x2={x2} y2={y2} class={cls} stroke-width={w} />
          <% {:disc, cx, cy, r, cls} -> %>
            <circle cx={cx} cy={cy} r={r} class={cls} />
          <% {:arc, d, cls} -> %>
            <path d={d} class={cls} fill="none" />
          <% {:ground, cx, cy, rx, ry} -> %>
            <ellipse cx={cx} cy={cy} rx={rx} ry={ry} class="sc-ground" />
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

  # Every part as {depth, shape}; sorted far to near, then stripped of depth.
  defp parts(pose, detail?) do
    pose
    |> segments(detail?)
    |> Enum.sort_by(&elem(&1, 0), :desc)
    |> Enum.map(&elem(&1, 1))
  end

  defp segments(%{kind: :altaz} = pose, detail?) do
    cam = camera()
    az = pose[:az_deg] || 0.0
    alt = pose[:alt_deg] || 0.0

    base = {0.0, 0.0, @pier_top}
    # the fork rises from the base; the altitude axis is horizontal, across the azimuth
    top = add(base, {0.0, 0.0, 0.3})
    across = {cos(az), -sin(az), 0.0}
    tube = from_alt_az(alt, az)

    running = pose[:running] || %{}

    List.flatten([
      ground(cam, detail?),
      if(detail?, do: legs(cam), else: []),
      [seg(base, {0.0, 0.0, 0.0}, "sc-pier", 6.0, cam)],
      [seg(base, top, "sc-pier", 5.0, cam)],
      [seg(sub(top, scale(across, 0.16)), add(top, scale(across, 0.16)), "sc-dec", 3.2, cam)],
      [seg(sub(top, scale(tube, @tube)), add(top, scale(tube, @tube)), "sc-tube", 10.0, cam)],
      arc_of(top, {0.0, 0.0, 1.0}, 0.34, "sc-spin-ra", running[:az], cam),
      arc_of(top, across, 0.3, "sc-spin-dec", running[:alt], cam),
      lamp(pose, cam)
    ])
  end

  defp segments(pose, detail?) do
    cam = camera()
    pole = from_alt_az(pose[:polar_alt] || 38.0, pose[:polar_az] || 0.0)
    east = normalize(cross({0.0, 0.0, 1.0}, pole)) |> fallback({1.0, 0.0, 0.0})

    h = pose[:ha_deg] || 0.0
    d = pose[:dec_deg] || 0.0

    pier = {0.0, 0.0, @pier_top}
    head = add(pier, scale(pole, @head))
    dec_axis = rotate(east, pole, -h)
    saddle = add(head, scale(dec_axis, @saddle))
    weight = sub(head, scale(dec_axis, @cw))
    tube = rotate(pole, dec_axis, d)

    running = pose[:running] || %{}

    List.flatten([
      ground(cam, detail?),
      if(detail?, do: legs(cam), else: []),
      # the pier, then the polar housing along the axis
      [seg(pier, {0.0, 0.0, 0.0}, "sc-pier", 6.0, cam)],
      [seg(sub(pier, scale(pole, 0.14)), head, "sc-ra", 6.5, cam)],
      # the Dec axis through the head, saddle one side and the weight shaft the other
      [seg(weight, saddle, "sc-dec", 3.6, cam)],
      [disc(weight, 7.5, "sc-weight", cam)],
      # the tube, centred on the saddle
      [seg(sub(saddle, scale(tube, @tube)), add(saddle, scale(tube, @tube)), "sc-tube", 10.0, cam)],
      [disc(add(saddle, scale(tube, @tube)), 3.2, "sc-aperture", cam)],
      arc_of(head, pole, 0.3, "sc-spin-ra", running[:ra], cam),
      arc_of(saddle, dec_axis, 0.26, "sc-spin-dec", running[:dec], cam),
      lamp(pose, cam)
    ])
  end

  defp ground(cam, true) do
    {x, y, z} = project({0.0, 0.0, 0.0}, cam)
    [{z + 10.0, {:ground, r1(x), r1(y), r1(@ground_r * @scale), r1(@ground_r * @scale * :math.sin(@cam_el * @deg))}}]
  end

  defp ground(_cam, false), do: []

  defp legs(cam) do
    for a <- [20.0, 140.0, 260.0] do
      foot = {@ground_r * sin(a), @ground_r * cos(a), 0.0}
      seg({0.0, 0.0, @pier_top}, foot, "sc-leg", 4.0, cam)
    end
  end

  # a motion arc around `axis` at `centre`, drawn only while that axis runs
  defp arc_of(_centre, _axis, _r, _cls, running, _cam) when running != true, do: []

  defp arc_of(centre, axis, r, cls, _running, cam) do
    {u1, u2} = perps(axis)

    pts =
      for i <- 0..12 do
        t = (i * 12 - 72) * @deg
        p = add(centre, scale(add(scale(u1, :math.cos(t)), scale(u2, :math.sin(t))), r))
        project(p, cam)
      end

    d =
      pts
      |> Enum.with_index()
      |> Enum.map_join(" ", fn {{x, y, _}, i} -> "#{if i == 0, do: "M", else: "L"}#{r1(x)},#{r1(y)}" end)

    {_, _, z} = project(centre, cam)
    [{z - 20.0, {:arc, d, cls}}]
  end

  defp lamp(%{tracking: t}, cam) when t in [:sidereal, :model] do
    {x, y, z} = project({0.0, 0.0, @pier_top - 0.12}, cam)
    [{z - 30.0, {:disc, r1(x), r1(y), 5.0, "sc-lamp"}}]
  end

  defp lamp(_, _), do: []

  # -- projection -----------------------------------------------------------------------

  defp seg(a, b, cls, w, cam) do
    {x1, y1, z1} = project(a, cam)
    {x2, y2, z2} = project(b, cam)
    {(z1 + z2) / 2, {:line, r1(x1), r1(y1), r1(x2), r1(y2), cls, w}}
  end

  defp disc(p, r, cls, cam) do
    {x, y, z} = project(p, cam)
    {z, {:disc, r1(x), r1(y), r, cls}}
  end

  defp camera do
    e = @cam_el * @deg
    a = @cam_az * @deg
    pos = {:math.cos(e) * :math.sin(a), :math.cos(e) * :math.cos(a), :math.sin(e)}
    f = neg(pos)
    r = normalize(cross(f, {0.0, 0.0, 1.0}))
    u = cross(r, f)
    {f, r, u}
  end

  # Orthographic: screen x right, y down; depth grows away from the camera.
  # The origin is the pier top, so the mount head sits near the middle of the
  # frame whatever the axes are doing and the drawing never wanders.
  defp project(v, {f, r, u}) do
    c = {0.0, 0.0, @pier_top}
    d = sub(v, c)
    {@scale * dot(d, r), -@scale * dot(d, u), dot(d, f)}
  end

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

  defp rotate({x, y, z} = v, {kx, ky, kz} = k, deg) do
    t = deg * @deg
    c = :math.cos(t)
    s = :math.sin(t)
    {cx, cy, cz} = cross(k, v)
    kd = (kx * x + ky * y + kz * z) * (1 - c)
    {x * c + cx * s + kx * kd, y * c + cy * s + ky * kd, z * c + cz * s + kz * kd}
  end

  defp perps(a) do
    {_, _, z} = a
    seed = if abs(z) < 0.9, do: {0.0, 0.0, 1.0}, else: {1.0, 0.0, 0.0}
    u1 = normalize(cross(a, seed))
    {u1, cross(a, u1)}
  end

  defp fallback({x, y, z} = v, alt) do
    if :math.sqrt(x * x + y * y + z * z) < 1.0e-6, do: alt, else: v
  end

  defp cross({ax, ay, az}, {bx, by, bz}), do: {ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx}
  defp dot({ax, ay, az}, {bx, by, bz}), do: ax * bx + ay * by + az * bz
  defp add({ax, ay, az}, {bx, by, bz}), do: {ax + bx, ay + by, az + bz}
  defp sub({ax, ay, az}, {bx, by, bz}), do: {ax - bx, ay - by, az - bz}
  defp scale({x, y, z}, s), do: {x * s, y * s, z * s}
  defp neg(v), do: scale(v, -1.0)

  defp normalize(v) do
    n = :math.sqrt(dot(v, v))
    if n < 1.0e-9, do: v, else: scale(v, 1 / n)
  end

  defp cos(deg), do: :math.cos(deg * @deg)
  defp sin(deg), do: :math.sin(deg * @deg)
  defp r1(x), do: Float.round(x * 1.0, 1)
end
