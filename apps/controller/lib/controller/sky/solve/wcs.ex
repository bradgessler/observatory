defmodule Controller.Sky.Solve.Wcs do
  @moduledoc """
  A plate solve's WCS: the FITS header astrometry.net writes (`solve.wcs`)
  that says, for every pixel of the solved image, where on the sky it is
  (TAN projection, with SIP distortion terms). Kept with the answer so the
  solve can be used afterwards (a stack, a catalogue star drawn on the
  picture) instead of only its centre and size (`docs/metadata.md`, Stage 2).

  A header here is a list of `{keyword, value}` in the file's order, WCS
  keywords only: `WCSAXES`, `CTYPE1/2`, `CUNIT1/2`, `EQUINOX`, `RADESYS`,
  `LONPOLE`, `LATPOLE`, `CRVAL1/2`, `CRPIX1/2`, `CD1_1` to `CD2_2`, `IMAGEW`,
  `IMAGEH`, and the SIP terms (`A_ORDER`, `A_p_q`, `B_*`, `AP_*`, `BP_*`).
  Pixels are FITS pixels: 1 is the centre of the first pixel, and row 1 is
  the first row of the image as it is stored (for the stills, the top of the
  picture the sensor's way up).

  `scale/2` carries a solve made on a copy `s` times smaller onto the full
  picture (the box solves a 1,500 px grey copy of the 6,000 px JPEG):
  `CRPIX' = (CRPIX - 0.5) * s + 0.5`, `CD' = CD / s`, and each SIP term
  `A_p_q' = A_p_q * s^(1 - p - q)` (the same for `B`, `AP`, `BP`).
  """

  @sip ~r/\A(A|B|AP|BP)_(\d+)_(\d+)\z/
  @orders ~w(A_ORDER B_ORDER AP_ORDER BP_ORDER)
  @linear ~w(WCSAXES CTYPE1 CTYPE2 CUNIT1 CUNIT2 EQUINOX RADESYS LONPOLE LATPOLE CRVAL1 CRVAL2 CRPIX1 CRPIX2 CD1_1 CD1_2 CD2_1 CD2_2 IMAGEW IMAGEH)

  @doc """
  The WCS from a header (`Controller.Fits.header_of/1`'s `[{key, value}]`): its WCS keywords in
  order, with `RADESYS = 'ICRS'` when the header names no frame (astrometry.net's index catalogues
  are ICRS; its `EQUINOX = 2000.0` stays). nil without a WCS.
  """
  def from_header(header) do
    kept = Enum.filter(header, fn {k, v} -> is_binary(k) and v != nil and wcs_key?(k) end) |> Enum.uniq_by(&elem(&1, 0))

    if List.keymember?(kept, "CRVAL1", 0) and List.keymember?(kept, "CD1_1", 0) do
      if List.keymember?(kept, "RADESYS", 0), do: kept, else: insert_after(kept, "EQUINOX", {"RADESYS", "ICRS"})
    end
  end

  defp wcs_key?(k), do: k in @linear or k in @orders or Regex.match?(@sip, k)

  defp insert_after(list, key, card) do
    case Enum.find_index(list, &(elem(&1, 0) == key)) do
      nil -> list ++ [card]
      i -> List.insert_at(list, i + 1, card)
    end
  end

  @doc "Read a WCS file astrometry.net wrote: `{:ok, %{wcs: header, software: \"astrometry.net 0.97\" | nil}}` or an error."
  def read(path) do
    with {:ok, bin} <- File.read(path),
         {:ok, header, _size} <- Controller.Fits.header_of(bin),
         wcs when is_list(wcs) <- from_header(header) || {:error, :no_wcs} do
      {:ok, %{wcs: wcs, software: software(header)}}
    end
  end

  # "HISTORY Git revision 0.97" is how solve-field says which astrometry.net it is
  defp software(header) do
    Enum.find_value(header, fn
      {"HISTORY", "Git revision " <> v} -> "astrometry.net " <> String.trim(v)
      _ -> nil
    end)
  end

  @doc """
  The same WCS for the picture `s` times bigger than the one solved (see the moduledoc), with
  `IMAGEW`/`IMAGEH` set to `size` (`{w, h}`) when given.
  """
  def scale(wcs, s, size \\ nil) when is_number(s) and s > 0 do
    Enum.map(wcs, fn
      {"CRPIX" <> _ = k, v} when is_number(v) -> {k, (v - 0.5) * s + 0.5}
      {"CD" <> _ = k, v} when is_number(v) -> {k, v / s}
      {"IMAGEW", v} -> {"IMAGEW", if(size, do: elem(size, 0), else: round(v * s))}
      {"IMAGEH", v} -> {"IMAGEH", if(size, do: elem(size, 1), else: round(v * s))}
      {k, v} = card when is_number(v) ->
        case Regex.run(@sip, k) do
          [_, _, p, q] -> {k, v * :math.pow(s, 1 - String.to_integer(p) - String.to_integer(q))}
          _ -> card
        end

      card ->
        card
    end)
  end

  @doc "The header as a JSON object in its order (`Jason.OrderedObject`)."
  def json(nil), do: nil
  def json(wcs), do: Jason.OrderedObject.new(wcs)

  @doc """
  Where on the sky FITS pixel `{x, y}` is, by this WCS (TAN, with SIP when it has it): `{ra_deg,
  dec_deg}`. For checking a solve and for drawing on a picture; the same sums as
  `wcs-xy2rd` and astropy.
  """
  def sky(wcs, {x, y}) do
    h = Map.new(wcs)
    {u, v} = {x - h["CRPIX1"], y - h["CRPIX2"]}
    {du, dv} = {sip(h, "A", u, v), sip(h, "B", u, v)}
    {u, v} = {u + du, v + dv}
    # intermediate world coordinates, degrees, then the gnomonic projection back onto the sphere
    xi = (h["CD1_1"] * u + h["CD1_2"] * v) * :math.pi() / 180
    eta = (h["CD2_1"] * u + h["CD2_2"] * v) * :math.pi() / 180
    {ra0, dec0} = {h["CRVAL1"] * :math.pi() / 180, h["CRVAL2"] * :math.pi() / 180}
    d = :math.cos(dec0) - eta * :math.sin(dec0)
    ra = ra0 + :math.atan2(xi, d)
    dec = :math.atan2(:math.sin(dec0) + eta * :math.cos(dec0), :math.sqrt(xi * xi + d * d))
    {Controller.Sky.Astro.norm360(ra * 180 / :math.pi()), dec * 180 / :math.pi()}
  end

  defp sip(h, name, u, v) do
    case h["#{name}_ORDER"] do
      n when is_integer(n) ->
        for p <- 0..n, q <- 0..(n - p), c = h["#{name}_#{p}_#{q}"], is_number(c), reduce: 0.0 do
          acc -> acc + c * :math.pow(u, p) * :math.pow(v, q)
        end

      _ ->
        0.0
    end
  end
end
