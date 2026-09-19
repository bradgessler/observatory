defmodule Controller.Sky.Joystick do
  @moduledoc """
  Turns "move the view up / down / left / right, as I see it" into rates for
  the two mount axes.

  An equatorial mount's axes are tilted to the pole, so "up" (toward the
  zenith) is a mix of RA and Dec that depends on where the scope points. We
  take the local Jacobian of (altitude, azimuth) with respect to (hour angle,
  declination) at the current pointing, invert it for the wanted on-sky
  direction, and scale so the faster axis runs at the chosen rate.

  Before home is set we don't know where the scope points, so `compass/3`
  offers the hand-controller convention instead: N/S toward/away from the
  pole, E/W along the sky's rotation — a pure sign mapping.
  """

  alias Controller.Sky.{Astro, Pointing}

  @type dir :: :up | :down | :left | :right
  @eps 0.05

  @doc "Sky-oriented: `[{:ra, rate}, {:dec, rate}]` (× sidereal) to move the view in `dir`. nil until homed."
  def sky(snap, ctx, dir, rate) do
    case Pointing.scope_radec(snap, ctx) do
      nil ->
        nil

      {ra_deg, dec_deg} ->
        %{site: site, now: now, pointing: p} = ctx
        lst = Astro.lst_deg(now, site.lon)
        h = Astro.hour_angle(lst, ra_deg)

        # Jacobian of (alt, az·cos alt) wrt (H, δ), degrees per degree
        {alt0, az0} = Astro.alt_az(ra_deg, dec_deg, site.lat, lst)
        {alt_h, az_h} = Astro.alt_az(ra_deg - @eps, dec_deg, site.lat, lst)   # H + eps  ⇔ RA − eps
        {alt_d, az_d} = Astro.alt_az(ra_deg, dec_deg + @eps, site.lat, lst)
        c = :math.cos(alt0 * :math.pi() / 180)
        j11 = (alt_h - alt0) / @eps
        j21 = Astro.norm180(az_h - az0) * c / @eps
        j12 = (alt_d - alt0) / @eps
        j22 = Astro.norm180(az_d - az0) * c / @eps
        det = j11 * j22 - j12 * j21

        if abs(det) < 1.0e-6 do
          nil
        else
          # wanted on-sky motion: (d_alt, d_az_on_sky); azimuth increases to the right when facing the object
          {want_alt, want_az} =
            case dir do
              :up -> {1.0, 0.0}
              :down -> {-1.0, 0.0}
              :right -> {0.0, 1.0}
              :left -> {0.0, -1.0}
            end

          d_h = (want_alt * j22 - want_az * j12) / det
          d_dec = (j11 * want_az - j21 * want_alt) / det

          # sky → axes: H = ra_axis·ha_sign (+180 on the flipped side, a constant); δ = 90 ∓ dec_axis·dec_sign
          flipped? = (snap.axes.dec.degrees - ctx.offset["dec"]) * p.dec_sign < 0
          d_ra_axis = d_h / p.ha_sign
          d_dec_axis = if(flipped?, do: d_dec, else: -d_dec) / p.dec_sign
          _ = h

          scale = rate / max(abs(d_ra_axis), abs(d_dec_axis))
          [{:ra, d_ra_axis * scale}, {:dec, d_dec_axis * scale}]
        end
    end
  end

  @doc "Compass convention: N/S = toward/away from the pole (Dec), E/W = along the sky's turn (RA)."
  def compass(snap, ctx, dir, rate) do
    p = ctx.pointing
    flipped? = snap != nil and snap.homed and (snap.axes.dec.degrees - ctx.offset["dec"]) * p.dec_sign < 0
    north = if(flipped?, do: 1, else: -1) * p.dec_sign

    case dir do
      :up -> [{:dec, north * rate}]
      :down -> [{:dec, -north * rate}]
      # east = decreasing hour angle
      :left -> [{:ra, -p.ha_sign * rate}]
      :right -> [{:ra, p.ha_sign * rate}]
    end
  end
end
