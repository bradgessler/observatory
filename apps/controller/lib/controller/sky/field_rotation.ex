defmodule Controller.Sky.FieldRotation do
  @moduledoc """
  How fast the picture turns about its middle while the mount tracks, and so how long an exposure can be before
  the corners smear.

  The camera turns with the mount's polar axis; the sky turns about the true pole. Seen from the target, the
  direction to the mount's pole drifts against the direction to the true pole as the night goes on, and that
  drift is the field's rotation. It is computed here exactly that way: the mount's axis is fixed to the ground
  (alt/az), so its place on the sky changes with sidereal time, and its position angle from the target is read a
  minute apart. Nothing about the size of the error is assumed.

  The same arithmetic covers every mount: an equatorial mount set down off the pole (17 October 2026: 10.6 degrees,
  the field turning about 2.5 degrees an hour on M33), a perfectly aligned one (no rotation), and an alt-az mount,
  whose "polar axis" points straight up. A camera rotator on an alt-az mount turns at this rate.

  The model tracker drives both axes, so a misaligned axis does not make stars drift; what is left is this.
  It depends on the exposure's length and where the target is, not on ISO. The axis comes from the star
  alignment's fit (`Controller.Sky.Model`, J2000 frame; the 0.15 degree to the pole of date is ignored).

      FieldRotation.rate_deg_per_h(%{alt: 32.7, az: 348.2}, 23.46, 30.66, %{lat: 37.34, lon: -121.64}, now)
      FieldRotation.max_exposure_s(rate, FieldRotation.corner_arcsec(2084), 1.0)
  """
  alias Controller.Sky.Astro

  @deg :math.pi() / 180
  # a 1 arcsec smear in the corners is well under any star this telescope makes
  @tolerance_arcsec 1.0

  def tolerance_arcsec, do: @tolerance_arcsec

  @doc "The field's rotation, degrees an hour (signed), for a mount whose polar axis points at `axis` (alt/az)."
  def rate_deg_per_h(%{alt: axis_alt, az: axis_az}, ra, dec, site, %DateTime{} = at) do
    pa = fn t -> axis_angle(axis_alt, axis_az, ra, dec, site, t) end
    Astro.norm180(pa.(DateTime.add(at, 60)) - pa.(at)) * 60
  end

  # the position angle, from the target, of where the mount's axis points on the sky at moment t
  defp axis_angle(alt, az, ra, dec, site, t) do
    {pra, pdec} = Astro.radec_from_altaz(alt, az, site.lat, Astro.lst_deg(t, site.lon))
    position_angle(ra, dec, pra, pdec)
  end

  @doc "The position angle of the second point seen from the first, degrees east of north."
  def position_angle(ra1, dec1, ra2, dec2) do
    da = (ra2 - ra1) * @deg
    {d1, d2} = {dec1 * @deg, dec2 * @deg}
    :math.atan2(:math.sin(da) * :math.cos(d2), :math.cos(d1) * :math.sin(d2) - :math.sin(d1) * :math.cos(d2) * :math.cos(da)) / @deg
  end

  @doc "How far the picture's corner is from its middle, arcseconds, for a sensor `w` x `h` mm at `focal_mm`."
  def corner_arcsec(focal_mm, w_mm \\ 23.5, h_mm \\ 15.6) when is_number(focal_mm) and focal_mm > 0,
    do: :math.atan(:math.sqrt(w_mm * w_mm + h_mm * h_mm) / 2 / focal_mm) / @deg * 3600

  @doc "How far a corner star moves during `exposure_s` at `rate_deg_per_h`, arcseconds."
  def smear_arcsec(rate_deg_per_h, exposure_s, corner_arcsec),
    do: abs(rate_deg_per_h) / 3600 * @deg * exposure_s * corner_arcsec

  @doc "The longest exposure that keeps the corners within `tolerance` arcsec; nil when the field doesn't turn."
  def max_exposure_s(rate_deg_per_h, corner_arcsec, tolerance \\ @tolerance_arcsec) do
    per_s = abs(rate_deg_per_h) / 3600 * @deg * corner_arcsec
    if per_s > 1.0e-9, do: tolerance / per_s
  end

  @doc """
  For mount `id` now (or `at`) and an exposure of `exposure_s`: what its alignment does to the picture.
  `%{axis_off_deg, rate_deg_per_h, corner_arcsec, smear_arcsec, max_exposure_s, tolerance_arcsec}`, or nil
  without a star alignment, a pointing or a focal length. Facts only: whether that is too much is for whoever
  reads it (the page, the stacking).
  """
  def for_mount(id, exposure_s, opts \\ []) do
    alias Controller.Sky.{Lineup, Model, Pointing}
    at = Keyword.get(opts, :at, DateTime.utc_now())
    site = Pointing.site()

    with %{} = m <- Lineup.model(id),
         m = Model.canonical(m),
         %{} = snap <- Mount.snapshot(id),
         {ra, dec} <- Pointing.scope_radec(snap, Pointing.context(at, id)),
         focal when is_number(focal) and focal > 0 <- Keyword.get_lazy(opts, :focal_mm, fn -> Controller.Settings.get("focal_length_mm") end) do
      rate = rate_deg_per_h(%{alt: m.axis_alt, az: m.axis_az}, ra, dec, site, at)
      corner = corner_arcsec(focal)
      tol = Keyword.get(opts, :tolerance_arcsec, @tolerance_arcsec)

      %{
        axis_off_deg: Float.round(Model.axis_error(m, site.lat) / 1, 2),
        rate_deg_per_h: Float.round(rate, 3),
        corner_arcsec: round(corner),
        smear_arcsec: is_number(exposure_s) && Float.round(smear_arcsec(rate, exposure_s, corner), 2),
        max_exposure_s: (max = max_exposure_s(rate, corner, tol)) && round(max),
        tolerance_arcsec: tol
      }
    else
      _ -> nil
    end
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end
end
