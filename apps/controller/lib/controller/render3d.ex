defmodule Controller.Render3D do
  @moduledoc """
  A small 3-D renderer that draws to SVG on the server: no WebGL, no
  library, nothing for the browser to run. A model is a list of faces (flat
  polygons, each with a material); `render/3` looks at them through a
  perspective camera, drops the faces turned away, shades each by how
  squarely it faces the light, and paints far to near, so nearer faces
  cover farther ones. What comes out is polygons for an `<svg>`:

      faces = Render3D.cylinder({0, 0, 0}, {0, 0, 1}, 0.1, :metal) ++ Render3D.box(...)
      cam = Render3D.camera({0, 0, 0.5}, az: 150, el: 20, distance: 4.5, focal: 310)
      for f <- Render3D.render(faces, cam), do: ~s(<polygon class="m-\#{f.mat} l\#{f.level}" points="\#{f.points}"/>)

  Shading is in steps (`level` 0 to 7), and a material is a CSS class, so
  the colour is the theme's: `.m-tube.l5` mixes the tube's ink with the
  background, and night mode turns the whole model red with everything else.

  Coordinates are east, north, up (x, y, z), the convention of the orb and
  the sky code. Faces wind counter-clockwise seen from outside; the shape
  builders here get that right, so culling and shading work.

  Painting far to near is the painter's algorithm: right for separate solid
  parts like a mount's, wrong only where two faces cut through each other,
  which a model of separate parts avoids.
  """

  @deg :math.pi() / 180
  @levels 8

  # -- shapes ---------------------------------------------------------------------------

  @doc """
  A cylinder from `a` to `b`, radius `r`, as `sides` flat faces round it and
  a cap at each end (`caps: false` leaves them off).
  """
  def cylinder(a, b, r, mat, opts \\ []) do
    n = Keyword.get(opts, :sides, 12)
    axis = normalize(sub(b, a))
    {u, w} = perps(axis)

    ring = fn c ->
      for i <- 0..(n - 1) do
        t = 2 * :math.pi() * i / n
        add(c, add(scale(u, r * :math.cos(t)), scale(w, r * :math.sin(t))))
      end
    end

    ra = ring.(a)
    rb = ring.(b)

    sides =
      for i <- 0..(n - 1) do
        j = rem(i + 1, n)
        {[Enum.at(ra, i), Enum.at(ra, j), Enum.at(rb, j), Enum.at(rb, i)], mat}
      end

    caps = if Keyword.get(opts, :caps, true), do: [{Enum.reverse(ra), Keyword.get(opts, :cap_a, mat)}, {rb, Keyword.get(opts, :cap_b, mat)}], else: []
    sides ++ caps
  end

  @doc """
  A box centred on `c`, its edges along `x` and `y` (directions; `z` is
  square to both), `size` its full lengths along them `{lx, ly, lz}`.
  """
  def box(c, x, y, {lx, ly, lz}, mat) do
    x = normalize(x)
    z = normalize(cross(x, y))
    y = cross(z, x)
    {x, y, z} = {scale(x, lx / 2), scale(y, ly / 2), scale(z, lz / 2)}
    p = fn sx, sy, sz -> c |> add(scale(x, sx)) |> add(scale(y, sy)) |> add(scale(z, sz)) end

    [
      {[p.(-1, -1, 1), p.(1, -1, 1), p.(1, 1, 1), p.(-1, 1, 1)], mat},
      {[p.(-1, -1, -1), p.(-1, 1, -1), p.(1, 1, -1), p.(1, -1, -1)], mat},
      {[p.(1, -1, -1), p.(1, 1, -1), p.(1, 1, 1), p.(1, -1, 1)], mat},
      {[p.(-1, -1, -1), p.(-1, -1, 1), p.(-1, 1, 1), p.(-1, 1, -1)], mat},
      {[p.(-1, 1, -1), p.(-1, 1, 1), p.(1, 1, 1), p.(1, 1, -1)], mat},
      {[p.(-1, -1, -1), p.(1, -1, -1), p.(1, -1, 1), p.(-1, -1, 1)], mat}
    ]
  end

  # -- the camera -----------------------------------------------------------------------

  @doc """
  A camera looking at `target` from compass bearing `az:` and height `el:`
  (degrees), `distance:` away, with `focal:` the scale of the picture (screen
  units for something one unit across at one unit away). The light comes from
  over the camera's left shoulder.
  """
  def camera(target, opts) do
    a = Keyword.get(opts, :az, 150.0) * @deg
    e = Keyword.get(opts, :el, 20.0) * @deg
    dist = Keyword.get(opts, :distance, 4.5)
    back = {:math.cos(e) * :math.sin(a), :math.cos(e) * :math.cos(a), :math.sin(e)}
    eye = add(target, scale(back, dist))
    f = normalize(sub(target, eye))
    r = normalize(cross(f, {0.0, 0.0, 1.0}))
    u = cross(r, f)
    light = normalize(add(add(scale(r, -0.55), scale(u, 0.75)), scale(f, -0.45)))
    %{eye: eye, f: f, r: r, u: u, focal: Keyword.get(opts, :focal, 300.0), light: light, ambient: Keyword.get(opts, :ambient, 0.28)}
  end

  @doc "Where a point lands on the screen, and how far away it is: `{x, y, depth}` (y down)."
  def project(p, %{eye: eye, f: f, r: r, u: u, focal: k}) do
    d = sub(p, eye)
    z = max(dot(d, f), 1.0e-3)
    {k * dot(d, r) / z, -k * dot(d, u) / z, z}
  end

  # -- drawing ----------------------------------------------------------------------------

  @doc """
  The faces that can be seen, far to near, each `%{mat, level, points,
  depth}`: `points` ready for an SVG `points` attribute, `level` the shade
  from 0 (in shadow) to 7 (square to the light).
  """
  def render(faces, cam, opts \\ []) do
    decimals = Keyword.get(opts, :decimals, 1)

    faces
    |> Enum.flat_map(fn {pts, mat} -> face(pts, mat, cam, decimals) end)
    |> Enum.sort_by(& &1.depth, :desc)
  end

  defp face([p0, p1, p2 | _] = pts, mat, cam, decimals) do
    n = normalize(cross(sub(p1, p0), sub(p2, p0)))
    c = centroid(pts)

    # turned away from the eye: the far side of a solid, never seen
    if dot(n, sub(cam.eye, c)) <= 0 do
      []
    else
      lit = max(dot(n, cam.light), 0.0)
      shade = cam.ambient + (1 - cam.ambient) * lit
      level = min(round(shade * (@levels - 1)), @levels - 1)
      screen = Enum.map(pts, &project(&1, cam))
      {_, _, depth} = project(c, cam)
      [%{mat: mat, level: level, depth: depth, points: Enum.map_join(screen, " ", fn {x, y, _} -> "#{r(x, decimals)},#{r(y, decimals)}" end)}]
    end
  end

  defp centroid(pts) do
    n = length(pts)
    {sx, sy, sz} = Enum.reduce(pts, {0.0, 0.0, 0.0}, &add/2)
    {sx / n, sy / n, sz / n}
  end

  defp r(x, d), do: Float.round(x * 1.0, d)

  # -- vectors -------------------------------------------------------------------------

  @doc "Turn `v` about the axis `k` (a unit vector) by `deg` degrees (Rodrigues)."
  def rotate({x, y, z} = v, {kx, ky, kz} = k, deg) do
    t = deg * @deg
    c = :math.cos(t)
    s = :math.sin(t)
    {cx, cy, cz} = cross(k, v)
    kd = (kx * x + ky * y + kz * z) * (1 - c)
    {x * c + cx * s + kx * kd, y * c + cy * s + ky * kd, z * c + cz * s + kz * kd}
  end

  @doc "Two unit vectors square to `a` and to each other, with `u × w = a`."
  def perps(a) do
    {_, _, z} = a
    seed = if abs(z) < 0.9, do: {0.0, 0.0, 1.0}, else: {1.0, 0.0, 0.0}
    u = normalize(cross(a, seed))
    {u, cross(a, u)}
  end

  def cross({ax, ay, az}, {bx, by, bz}), do: {ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx}
  def dot({ax, ay, az}, {bx, by, bz}), do: ax * bx + ay * by + az * bz
  def add({ax, ay, az}, {bx, by, bz}), do: {ax + bx, ay + by, az + bz}
  def sub({ax, ay, az}, {bx, by, bz}), do: {ax - bx, ay - by, az - bz}
  def scale({x, y, z}, s), do: {x * s, y * s, z * s}

  def normalize(v) do
    n = :math.sqrt(dot(v, v))
    if n < 1.0e-12, do: v, else: scale(v, 1 / n)
  end
end
