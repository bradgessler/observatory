defmodule Controller.StillCamera.Cloud do
  @moduledoc """
  Is there cloud in this picture? Thin cloud makes the same stars dimmer and
  the sky brighter at once (a lamp would only brighten the sky; a focus
  that has slipped only dims the stars). So each picture's stars are held
  against the same stars in the clearest picture of this field so far:

      {sky, field} = Cloud.judge(field, %{stars: Cloud.light(pgm, marks), sky: background, place: place})
      sky
      #=> %{transparency: 0.74, cloud: true, stars: 12, sky_ratio: 1.47}

  **Transparency** is how much of their light the stars still have: the
  median, over the stars found in both, of a star's light now over its light
  in the clearest picture. 1.0 is as clear as this field has been seen; the
  first picture of a field is 1.0 by definition, and a clearer one later
  takes its place as the yardstick.

  **Cloud** is transparency under `1 - dimmer` (0.2: stars more than 20
  percent dimmer) while the sky round those stars is more than `sky` times
  as bright as it was in the clearest picture (1.1). Or the stars it knew
  are gone altogether and the whole sky is `lost_sky` times as bright
  (1.5): thick cloud, with no transparency to give.

  **A star's light** (`light/3`) is what stands above the sky in a small
  disc round it, on the grey copy the box already measures. A JPEG's levels
  are not light: the camera bends them (bright things are squeezed), and a
  star's core read in levels loses less to cloud than it really did. So
  levels are straightened first with a plain power curve (`gamma:` 2.2).
  Saturated stars are left out: their tops are cut off.

  **A field** is the stars seen from one place at one exposure. It starts
  again when the pictures come from another camera or through another
  mount, when the target's name or the camera's ISO or shutter speed
  changes, or when the mount has slewed further than the field is wide
  since the picture before (`field_deg:`; without it, any slew). A field
  the pointing drifts or is nudged across is followed: each star's place is
  where it was last seen.

  Checked against the night it was written for (3 to 4 October 2026: 109
  frames of M31 at 20 s through passing cloud, each held against the
  stacker's own transparency from the RAW files). The two agree to 0.05
  rms. Of the 60 frames the stacker put under 0.8, 56 are flagged (the four
  missed are between 0.74 and 0.80); of the 43 at 0.8 or better, two are
  (0.81 and 0.83); all six too clouded for the stacker to measure are; and
  of the 38 frames the stack used, none. Of the 26 frames of M15 the same
  night, which the stacker has at 0.85 or better, none.

  Pure: numbers in, numbers out. Nothing here raises on odd input.
  """

  alias Controller.ScopeCamera.Image

  @dimmer 0.2
  @sky 1.1
  @lost_sky 1.5
  @min_stars 3
  @tolerance 5
  @keep 60
  @window 15
  @radius 4
  @saturation 250
  @gamma 2.2

  # -- a star's light ---------------------------------------------------------------------------

  @doc """
  The light of each star at `stars` (`[%{x, y}]`, as `Controller.ScopeCamera.analyse/2`
  marks them) in `image` (`%{w, h, px}` or a PGM): `[%{x, y, light, sky}]`, in
  the order given. `light` is what stands above the sky in a disc round the
  star, and `sky` the level of the sky round it. A star is left out when its
  window doesn't fit in the picture, when it is saturated, or when nothing
  stands above the sky there.

  Options: `window:` the side of the square read round each star, in pixels
  (#{@window}: its border is the sky); `radius:` of the disc the light is
  added up in (#{@radius}); `saturation:` the level at which a star is left
  out (#{@saturation}); `gamma:` the power that straightens the JPEG's levels
  into light (#{@gamma}; 1.0 leaves them as they are).
  """
  def light(image, stars, opts \\ []) do
    with {:ok, %{w: w, h: h, px: px}} <- image(image), true <- is_list(stars) do
      size = Keyword.get(opts, :window, @window)
      half = div(size, 2)
      radius = Keyword.get(opts, :radius, @radius)
      saturation = Keyword.get(opts, :saturation, @saturation)
      gamma = Keyword.get(opts, :gamma, @gamma)
      # every level as light, worked out once
      straight = List.to_tuple(for v <- 0..255, do: straighten(v, gamma))

      for %{x: x, y: y} <- stars, is_number(x) and is_number(y), cx = round(x), cy = round(y), cx - half >= 0 and cy - half >= 0 and cx + half < w and cy + half < h,
          {light, sky} <- [disc(px, w, cx - half, cy - half, size, half, radius, saturation, straight, gamma)],
          do: %{x: cx, y: cy, light: light, sky: sky}
    else
      _ -> []
    end
  rescue
    _ -> []
  end

  defp straighten(level, gamma), do: 255.0 * :math.pow(level / 255.0, gamma)

  # The light above the sky in the disc at the window's middle, and the sky's level. The sky is
  # read from the window's border. Nothing is thresholded: light counted only above a noise floor
  # shrinks as the sky brightens, which is the very thing being measured.
  defp disc(px, w, x0, y0, size, half, radius, saturation, straight, gamma) do
    rows = for j <- 0..(size - 1), do: :binary.bin_to_list(px, (y0 + j) * w + x0, size)
    border = Enum.sort(hd(rows) ++ List.last(rows) ++ Enum.flat_map(Enum.slice(rows, 1..-2//1), &[hd(&1), List.last(&1)]))
    under = straighten(median(border), gamma)

    {sum, top} =
      for {row, j} <- Enum.with_index(rows), {v, i} <- Enum.with_index(row), (i - half) * (i - half) + (j - half) * (j - half) <= radius * radius, reduce: {0.0, 0} do
        {sum, top} -> {sum + elem(straight, v) - under, max(top, v)}
      end

    # the sky's level to a fraction of a step: the mean of the border's darker three quarters (a
    # neighbour's light lies in the brightest of it), where a median only ever says a whole level
    dark = Enum.take(border, max(div(length(border) * 3, 4), 1))
    if top < saturation and sum > 0, do: {sum, Enum.sum(dark) / length(dark)}
  end

  # -- a picture against its field --------------------------------------------------------------

  @doc """
  Hold a picture against its field. `frame` is `%{stars: [%{x, y, light,
  sky}], sky: level}` (what `light/3` gives, and the whole picture's
  background), with `place:` when it is known where and how it was taken:
  `%{mount: id, target: name, settings: {iso, shutter}, slewed: {ra_deg,
  dec_deg}}`, `slewed` being how far each axis has turned in slews, added up
  (only its change matters).

  Returns `{verdict, field}`: the field is handed back in with the next
  picture (`nil` for the first), and the verdict is

    * `transparency`: 0 to about 1, or `nil` when it can't be said (no stars,
      or none of the stars it knew);
    * `cloud`: `true`, `false`, or `nil` when it can't be said;
    * `stars`: how many stars the transparency is from;
    * `sky_ratio`: the sky against the clearest picture's (round those stars;
      the whole picture's when there are none);
    * `first`: `true` for the picture a field starts with.

  Options: `dimmer:` (#{@dimmer}), `sky:` (#{@sky}), `lost_sky:` (#{@lost_sky}),
  `min_stars:` the fewest stars a transparency is taken from (#{@min_stars}),
  `tolerance:` how far, in pixels, a star may be from where it was last seen
  (#{@tolerance}), `keep:` how many stars a field remembers (#{@keep}), and
  `field_deg:` the field's width, for telling a nudge from a new field.
  """
  def judge(field, frame, opts \\ [])

  def judge(field, %{stars: stars, sky: sky} = frame, opts) when is_list(stars) and is_number(sky) do
    stars = Enum.filter(stars, &match?(%{x: x, y: y, light: l} when is_number(x) and is_number(y) and is_number(l) and l > 0, &1))
    place = frame[:place]

    # a field with no stars in it is no yardstick: the first picture that has some starts one
    if is_map(field) and field[:stars] not in [nil, []] and not moved?(field[:place], place, opts[:field_deg]),
      do: against(field, stars, sky, place, opts),
      else: start(stars, sky, place)
  end

  def judge(field, _frame, _opts), do: {%{transparency: nil, cloud: nil, stars: 0, sky_ratio: nil}, field}

  # a field's first picture is its own yardstick
  defp start(stars, sky, place) do
    field = %{place: place, sky: sky, n: 1, stars: Enum.map(stars, &%{x: &1.x, y: &1.y, light: &1.light, sky: &1[:sky], seen: 1})}
    known? = stars != []
    {%{transparency: if(known?, do: 1.0), cloud: if(known?, do: false), stars: length(stars), sky_ratio: 1.0, first: true}, field}
  end

  defp against(field, stars, sky, place, opts) do
    tolerance = Keyword.get(opts, :tolerance, @tolerance)
    min_stars = Keyword.get(opts, :min_stars, @min_stars)
    n = field.n + 1

    # each star, brightest first, with the nearest one the field knows that no brighter star has taken
    {pairs, _taken} =
      stars
      |> Enum.sort_by(& &1.light, :desc)
      |> Enum.reduce({[], MapSet.new()}, fn star, {pairs, taken} ->
        case nearest(Enum.reject(field.stars, &MapSet.member?(taken, {&1.x, &1.y})), star, tolerance) do
          nil -> {pairs, taken}
          known -> {[{known, star} | pairs], MapSet.put(taken, {known.x, known.y})}
        end
      end)

    ratios = for {known, star} <- pairs, do: star.light / known.light
    # the sky where those stars are, against the sky that was there; the whole picture's when no star says
    skies = for {known, star} <- pairs, is_number(known[:sky]) and is_number(star[:sky]) and known.sky > 0, do: star.sky / known.sky
    whole = if field.sky > 0, do: sky / field.sky
    sky_ratio = if skies == [], do: whole, else: median(skies)

    {transparency, cloud} =
      cond do
        length(ratios) >= min_stars ->
          t = median(ratios)
          {t, t < 1 - Keyword.get(opts, :dimmer, @dimmer) and is_number(sky_ratio) and sky_ratio > Keyword.get(opts, :sky, @sky)}

        # the stars it knew are gone, with none in their place, and the sky is far brighter: thick
        # cloud, nothing to measure
        length(stars) < min_stars and length(field.stars) >= min_stars and is_number(whole) and whole >= Keyword.get(opts, :lost_sky, @lost_sky) ->
          {nil, true}

        # other stars where those were (the pointing has jumped), or too few to go by: it can't be said
        true ->
          {nil, nil}
      end

    # A clearer picture than the clearest so far is the yardstick now: its stars' light and its sky.
    clearer? = is_number(transparency) and transparency > 1.0
    # a star not seen before joins as bright as it would be in the clearest picture
    scale = if is_number(transparency) and transparency > 0, do: min(transparency, 1.0), else: 1.0
    matched = Map.new(pairs, fn {known, star} -> {{known.x, known.y}, star} end)

    kept =
      Enum.map(field.stars, fn known ->
        case matched[{known.x, known.y}] do
          nil -> known
          star when clearer? -> %{known | x: star.x, y: star.y, light: star.light, sky: star[:sky], seen: n}
          star -> %{known | x: star.x, y: star.y, seen: n}
        end
      end)

    sky_scale = if is_number(sky_ratio) and sky_ratio > 1.0, do: sky_ratio, else: 1.0
    new = for star <- stars, nearest(kept, star, tolerance) == nil, do: %{x: star.x, y: star.y, light: star.light / scale, sky: is_number(star[:sky]) && star.sky / sky_scale || nil, seen: n}

    field = %{
      field
      | n: n,
        place: place || field.place,
        sky: if(clearer?, do: sky, else: field.sky),
        stars: (kept ++ new) |> Enum.sort_by(& &1.seen, :desc) |> Enum.take(Keyword.get(opts, :keep, @keep))
    }

    {%{transparency: transparency && Float.round(transparency / 1, 3), cloud: cloud, stars: length(ratios), sky_ratio: sky_ratio && Float.round(sky_ratio / 1, 3)}, field}
  end

  defp nearest(known, %{x: x, y: y}, tolerance) do
    known
    |> Enum.map(&{(&1.x - x) * (&1.x - x) + (&1.y - y) * (&1.y - y), &1})
    |> Enum.filter(fn {d, _} -> d <= tolerance * tolerance end)
    |> Enum.min_by(&elem(&1, 0), fn -> nil end)
    |> case do
      {_, star} -> star
      nil -> nil
    end
  end

  @doc """
  Has the telescope gone to another field between two places, or the camera
  to another exposure? Another camera, another mount, another target's name,
  another ISO or shutter speed, or slews that add up to more than
  `field_deg` (any slew at all when the field's width isn't known). What a
  place doesn't say (`nil`) is taken to be the same.
  """
  def moved?(%{} = from, %{} = to, field_deg) do
    other? = fn key -> from[key] != nil and to[key] != nil and from[key] != to[key] end
    Enum.any?([:camera, :mount, :target, :settings], other?) or further?(from[:slewed], to[:slewed], field_deg)
  end

  def moved?(_, _, _), do: false

  defp further?({ra0, dec0}, {ra1, dec1}, field_deg) when is_number(ra0) and is_number(dec0) and is_number(ra1) and is_number(dec1) do
    # the axes' own degrees: on the sky an hour-axis turn is this much or less, so a move is never
    # taken for smaller than it was
    turned = :math.sqrt((ra1 - ra0) * (ra1 - ra0) + (dec1 - dec0) * (dec1 - dec0))
    if is_number(field_deg) and field_deg > 0, do: turned > field_deg, else: turned > 0
  end

  defp further?(_, _, _), do: false

  defp median(values) do
    sorted = Enum.sort(values)
    n = length(sorted)
    if rem(n, 2) == 1, do: Enum.at(sorted, div(n, 2)), else: (Enum.at(sorted, div(n, 2) - 1) + Enum.at(sorted, div(n, 2))) / 2
  end

  defp image(%{w: w, h: h, px: px} = img) when is_integer(w) and is_integer(h) and w > 0 and h > 0 and is_binary(px) and byte_size(px) >= w * h, do: {:ok, img}
  defp image(pgm) when is_binary(pgm), do: Image.from_pgm(pgm)
  defp image(_), do: :error
end
