defmodule Controller.Sky.HorizonScan do
  @moduledoc """
  Turn a solved sky photo plus the traced sky/obstruction boundary into a
  horizon profile: altitude of the tree line per compass sector.

  Inputs: the plate solution (center RA/Dec, pixel scale, orientation) and,
  from the browser, the boundary as a list of `{x_frac, y_frac}` points —
  for each image column, how far down the frame the sky stops. Small-angle
  gnomonic math around the solved center; a phone's 70° field bends that a
  little, which is fine for "trees start about here".
  """

  alias Controller.Settings
  alias Controller.Sky.Astro

  @deg :math.pi() / 180

  @doc """
  Returns `%{"N" => alt, ...}` for sectors the photo covers (others absent),
  where alt is the highest obstruction seen in that sector.
  """
  def profile(solution, boundary, %{lat: lat, lon: lon}, %DateTime{} = taken_at, {w_px, h_px}) do
    lst = Astro.lst_deg(taken_at, lon)
    scale = solution.pixscale_arcsec / 3600
    # image up direction relative to north, degrees east of north
    theta = (solution.orientation_deg || 0.0) * @deg
    parity = if solution.parity == 1, do: -1, else: 1

    boundary
    |> Enum.map(fn {xf, yf} ->
      # pixel offsets from center, in degrees; y down in the image
      dx = (xf - 0.5) * w_px * scale * parity
      dy = (0.5 - yf) * h_px * scale
      # rotate by orientation into east/north offsets on the sky
      east = dx * :math.cos(theta) - dy * :math.sin(theta)
      north = dx * :math.sin(theta) + dy * :math.cos(theta)
      dec = solution.dec_deg + north
      ra = solution.ra_deg + east / max(:math.cos(dec * @deg), 0.05)
      Astro.alt_az(Astro.norm360(ra), dec, lat, lst)
    end)
    |> Enum.group_by(fn {_alt, az} -> sector(az) end, fn {alt, _az} -> alt end)
    |> Map.new(fn {s, alts} -> {s, alts |> Enum.max() |> max(0.0) |> min(89.0) |> round()} end)
  end

  @doc "Merge a scanned profile into the saved horizon: scanned sectors win."
  def merge(existing, scanned), do: Map.merge(existing, scanned)

  defp sector(az), do: Enum.at(Settings.sectors(), round(Astro.norm360(az) / 45) |> rem(8))
end
