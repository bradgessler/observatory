defmodule Controller.Optical.Rig do
  @moduledoc """
  The mount as the camera sees it, live: from a sweep's two fitted axes,
  the three lines that matter — polar axis, Dec axis, tube — at whatever
  the encoders say right now, projected into the picture.

  The polar axis is fixed in the camera's world. The Dec axis turns about it
  as RA turns, from where the sweep found it at its reference encoder angle.
  The tube turns about the Dec axis as Dec turns, starting from "along the
  polar axis" at the home Dec angle — so the tube line is only as right as
  home was set (counterweight down, tube at the pole); the two axes do not
  depend on that.

  Depth: each sweep fixed its axis point at unit depth independently. A
  GEM's axes meet, so the Dec axis is slid along its own ray to the point
  nearest the polar axis; that puts both in one frame up to one overall
  scale, which projection does not care about.
  """

  alias Controller.Optical.Axis3D

  @deg :math.pi() / 180

  @doc "Build a rig from a stored sweep result (string-keyed, as in Settings) and the encoder angles it was taken at. nil if a fit is missing or a tilt unresolved."
  def from_sweep(sweep, ref_encoders, hfov \\ nil)

  # the joint fit is perpendicular by construction and free of the lone-axis degeneracy
  def from_sweep(%{"pair" => %{"polar" => %{} = ra, "dec" => %{} = dec}} = sweep, ref_encoders, hfov) do
    from_sweep(sweep |> Map.delete("pair") |> put_in(["ra", "fit"], ra) |> put_in(["dec", "fit"], dec), ref_encoders, hfov)
  end

  def from_sweep(%{"ra" => %{"fit" => %{} = ra}, "dec" => %{"fit" => %{} = dec}} = sweep, ref_encoders, hfov) do
    if ra["tilt_ambiguous"] or dec["tilt_ambiguous"] do
      nil
    else
      w = sweep["ra"]["w"]
      h = sweep["ra"]["h"]
      cam = Axis3D.camera(w, h, hfov || sweep["hfov_deg"] || 70)
      p = List.to_tuple(ra["dir"])
      cp = List.to_tuple(ra["point"])
      d = List.to_tuple(dec["dir"])
      cd_ray = List.to_tuple(dec["point"])
      # slide the Dec axis point along the camera ray through it to the point nearest the polar axis
      cd = nearest_on_ray_to_line(cd_ray, cp, p)

      %{
        cam: cam,
        w: w,
        h: h,
        scale: sweep["ra"]["scale"] || 1,
        polar: %{dir: p, point: cp, sense: ra["sense"] || 1.0},
        dec: %{dir: d, point: cd, sense: dec["sense"] || 1.0},
        ref: ref_encoders
      }
    end
  end

  def from_sweep(_, _, _), do: nil

  @doc """
  The three lines for encoder angles `%{ra: deg, dec: deg}`, each as two image
  points `{{x1, y1}, {x2, y2}}` in the sweep frame's pixels, plus the current
  Dec axis direction. `dec_home` is the Dec encoder angle at which the tube
  lies along the polar axis (0 once home is set properly).
  """
  def pose(rig, %{ra: ra, dec: dec}, opts \\ []) do
    dec_home = opts[:dec_home] || 0.0
    dec_sign = opts[:dec_sign] || -1
    d_ra = (ra - rig.ref.ra) * @deg * rig.polar.sense
    p = rig.polar.dir
    cp = rig.polar.point

    # the Dec axis and its point swing about the polar axis with RA
    d_now = rotate(rig.dec.dir, p, d_ra)
    cd_now = add(cp, rotate(sub(rig.dec.point, cp), p, d_ra))

    # the tube: along the polar axis at home Dec, turned about the Dec axis since
    pole_distance = (dec - dec_home) * @deg * dec_sign * rig.dec.sense
    tube = rotate(p, d_now, pole_distance)

    %{
      polar: line(cp, p, rig.cam, 0.6),
      dec: line(cd_now, d_now, rig.cam, 0.45),
      tube: line(cd_now, tube, rig.cam, 0.7),
      dec_dir: d_now,
      tube_dir: tube
    }
  end

  # two projected points either side of `point` along `dir`
  defp line(point, dir, cam, half) do
    a = project(sub(point, scale(dir, half)), cam)
    b = project(add(point, scale(dir, half)), cam)
    {a, b}
  end

  defp project({x, y, z}, cam) when z > 0.05, do: {cam.f * x / z + cam.cx, cam.f * y / z + cam.cy}
  defp project({x, y, _}, cam), do: {cam.f * x / 0.05 + cam.cx, cam.f * y / 0.05 + cam.cy}

  # point on the ray (through the origin and r) nearest the line (through q along u)
  defp nearest_on_ray_to_line(r, q, u) do
    # closest points between line1: t*r and line2: q + s*u
    a = dot(r, r)
    b = dot(r, u)
    c = dot(u, u)
    d = dot(r, q)
    e = dot(u, q)
    den = a * c - b * b

    t = if abs(den) < 1.0e-9, do: 1.0, else: (d * c - e * b) / den
    scale(r, max(t, 0.1))
  end

  # Rodrigues' rotation of v about unit axis k by angle
  defp rotate(v, k, angle) do
    c = :math.cos(angle)
    s = :math.sin(angle)
    add(add(scale(v, c), scale(cross(k, v), s)), scale(k, dot(k, v) * (1 - c)))
  end

  defp dot({a, b, c}, {d, e, f}), do: a * d + b * e + c * f
  defp add({a, b, c}, {d, e, f}), do: {a + d, b + e, c + f}
  defp sub({a, b, c}, {d, e, f}), do: {a - d, b - e, c - f}
  defp scale({a, b, c}, k), do: {a * k, b * k, c * k}
  defp cross({a, b, c}, {d, e, f}), do: {b * f - c * e, c * d - a * f, a * e - b * d}
end
