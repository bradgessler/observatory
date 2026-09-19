defmodule Controller.Sky.Lineup do
  @moduledoc """
  The star alignment: set the mount down anyhow, centre a few stars you can name,
  and the software works out how the mount is really sitting. Holds the
  samples (encoders + what the tube was on, when) and the fitted model, per
  mount, in Settings; says which star to do next and how good things are.

      Lineup.add(snap, obj)        # "that's it" — the tube is on obj right now
      Lineup.model(mount_id)       # fitted params or nil
      Lineup.status(mount_id)      # %{n, rms_arcmin, axis_off_deg, good_for: [...]}
      Lineup.next(mount_id, ctx)   # the star to do next, with why
      Lineup.guess(snap, ctx)      # "you're probably on …" from the current pointing
      Lineup.clear(mount_id)
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Model, Pointing, Stars}

  @key "lineup"

  # What the fit is good enough for, by rms. Same words as the docs.
  @goals [
    {"just look", 30.0, "an object lands in a low-power eyepiece"},
    {"Moon and planets", 10.0, "quick snaps, exposures under a second"},
    {"deep sky", 2.0, "real exposures — also needs the axis near the pole"}
  ]

  def goals, do: @goals

  # -- samples ------------------------------------------------------------------------------

  @doc "Record that the tube is centred on `obj` (`%{ra_deg, dec_deg, name}`) right now; refits."
  def add(%{id: id, axes: axes} = snap, obj, now \\ DateTime.utc_now()) do
    site = Pointing.site()
    lst = Astro.lst_deg(now, site.lon)
    {alt, az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, site.lat, lst)

    sample = %{
      "name" => obj.name,
      "at" => DateTime.to_iso8601(now),
      "theta_ra" => axes.ra.degrees / 1,
      "theta_dec" => axes.dec.degrees / 1,
      "ra_deg" => obj.ra_deg / 1,
      "dec_deg" => obj.dec_deg / 1,
      "alt" => alt,
      "az" => az
    }

    # the encoders were re-zeroed since the last star: those samples belong
    # to another reference and would poison this one
    home_at = Map.get(snap, :homed_at)
    stale = samples(id) != [] and home_at != nil and entry(id)["home_at"] != home_at

    if stale do
      Telescope.Events.emit(:lineup, :reset, %{id: id, why: "axes re-zeroed"})
      put_samples(id, [])
    end

    put_samples(id, samples(id) ++ [sample], home_at)
    Telescope.Events.emit(:lineup, :star, %{id: id, name: obj.name, theta_ra: sample["theta_ra"], theta_dec: sample["theta_dec"]})
    refit(id)
  end

  defp entry(id), do: Settings.get(@key, %{}) |> Map.get(id, %{})

  @doc "Forget one sample by index; refits."
  def drop(id, index) do
    put_samples(id, List.delete_at(samples(id), index))
    refit(id)
  end

  @doc "Forget everything for this mount."
  def clear(id) do
    all = Settings.get(@key, %{})
    Settings.put(@key, Map.delete(all, id))
    :ok
  end

  def samples(id), do: Settings.get(@key, %{}) |> Map.get(id, %{}) |> Map.get("samples", [])

  @doc """
  The fitted model for a mount, as atom-keyed params (with the axis signs it
  was fitted under), or nil — also nil when the axes were re-zeroed since the
  stars were taken: the model counts from the old zero.
  """
  def model(id) do
    e = entry(id)

    case e["model"] do
      %{"axis_alt" => a, "axis_az" => z, "off_ra" => r, "off_dec" => d} ->
        if stale?(id, e),
          do: nil,
          else: %{axis_alt: a / 1, axis_az: z / 1, off_ra: r / 1, off_dec: d / 1, signs: signs_of(e)}

      _ ->
        nil
    end
  end

  @doc "Were the axes zeroed again after these stars were taken?"
  def stale?(id, e \\ nil) do
    e = e || entry(id)

    case {e["home_at"], safe_snapshot(id)} do
      {nil, _} -> false
      {_, nil} -> false
      {at, %{homed_at: now_at}} when is_integer(now_at) -> at != now_at
      _ -> false
    end
  end

  defp signs_of(e) do
    case e["signs"] do
      %{"ha_sign" => h, "dec_sign" => d} when h in [-1, 1] and d in [-1, 1] -> %{ha_sign: h, dec_sign: d}
      _ -> Pointing.pointing()
    end
  end

  defp safe_snapshot(id) do
    Mount.snapshot(id)
  catch
    :exit, _ -> nil
  end

  @doc "Numbers for the page and the mode chip."
  def status(id) do
    entry = entry(id)
    stale = stale?(id, entry)
    n = if stale, do: 0, else: length(Map.get(entry, "samples", []))
    rms = Map.get(entry, "rms_arcmin")
    lat = Pointing.site().lat
    m = model(id)

    %{
      n: n,
      stale?: stale,
      rms_arcmin: rms,
      worst_arcmin: Map.get(entry, "worst_arcmin"),
      residuals_arcmin: Map.get(entry, "residuals_arcmin", []),
      axis_off_deg: m && Model.axis_error(m, lat),
      axis_words: m && axis_words(m, lat),
      # one or two stars fit exactly whatever they are; only three or more can be judged
      good_for: if(rms && n >= 3, do: for({g, lim, _} <- @goals, rms <= lim, do: g), else: []),
      signs_corrected?: Map.get(entry, "signs_corrected", false),
      solved?: m != nil
    }
  end

  defp refit(id) do
    all = Settings.get(@key, %{})
    old = Map.get(all, id, %{})
    samples = Map.get(old, "samples", [])
    signs = signs_of(old)
    site = Pointing.site()
    start = Model.ideal(site.lat)

    # alt/az are recomputed from RA/Dec and the time for the site in force
    # now, so setting the site after the first star does not strand it
    fit_samples =
      Enum.map(samples, fn s ->
        {alt, az} =
          with ra when is_number(ra) <- s["ra_deg"],
               dec when is_number(dec) <- s["dec_deg"],
               {:ok, at, _} <- DateTime.from_iso8601(s["at"] || "") do
            Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(at, site.lon))
          else
            _ -> {s["alt"], s["az"]}
          end

        %{theta_ra: s["theta_ra"], theta_dec: s["theta_dec"], alt: alt, az: az}
      end)

    # once a sign was corrected during this star alignment, keep saying so
    corrected_before = old["signs_corrected"] == true

    entry =
      case fit_with_signs(fit_samples, signs, start) do
        {:ok, p, q} ->
          used = q[:signs_corrected] || signs

          %{
            "samples" => samples,
            "home_at" => old["home_at"],
            "signs" => %{"ha_sign" => used.ha_sign, "dec_sign" => used.dec_sign},
            "model" => %{"axis_alt" => p.axis_alt, "axis_az" => p.axis_az, "off_ra" => p.off_ra, "off_dec" => p.off_dec},
            "rms_arcmin" => q.rms_arcmin,
            "worst_arcmin" => q.worst_arcmin,
            "residuals_arcmin" => q.residuals_arcmin,
            "signs_corrected" => q[:signs_corrected] != nil or corrected_before,
            "at" => DateTime.to_iso8601(DateTime.utc_now())
          }

        {:error, _} ->
          %{"samples" => samples, "home_at" => old["home_at"]}
      end

    Settings.put(@key, Map.put(all, id, entry))
    status(id)
  end

  # The configured axis signs are a guess until the real sky says otherwise.
  #
  # A wrong RA sign cannot be absorbed by the geometry: with three or more
  # stars it shows as degrees of disagreement, so the other combinations are
  # tried and a far better one is adopted. A wrong Dec sign *is* absorbed —
  # it comes out as an RA offset near 180°, which means the model thinks the
  # counterweight is up when it is down and would pick the wrong side of the
  # pier for every goto. Flip it and refit. Either way the modes chip says so.
  defp fit_with_signs(fit_samples, signs, start) do
    case fit_with_ra_sign(fit_samples, signs, start) do
      {:ok, p, q, sg} when abs(p.off_ra) > 90 and abs(p.off_ra) < 270 ->
        flipped = %{sg | dec_sign: -sg.dec_sign}

        case Model.fit(fit_samples, flipped, start) do
          {:ok, p2, q2} ->
            p2 = %{p2 | off_ra: Astro.norm180(p2.off_ra)}

            if q2.rms_arcmin <= q.rms_arcmin + 0.5 and abs(p2.off_ra) <= 90 do
              Settings.put("pointing", %{"ha_sign" => flipped.ha_sign, "dec_sign" => flipped.dec_sign})
              {:ok, p2, Map.put(q2, :signs_corrected, flipped)}
            else
              {:ok, p, if(sg == signs, do: q, else: Map.put(q, :signs_corrected, sg))}
            end

          _ ->
            {:ok, p, if(sg == signs, do: q, else: Map.put(q, :signs_corrected, sg))}
        end

      {:ok, p, q, sg} ->
        {:ok, p, if(sg == signs, do: q, else: Map.put(q, :signs_corrected, sg))}

      other ->
        other
    end
  end

  defp fit_with_ra_sign(fit_samples, signs, start) do
    case Model.fit(fit_samples, signs, start) do
      {:ok, _p, %{rms_arcmin: rms}} = first when length(fit_samples) >= 3 and rms > 30.0 ->
        others = for h <- [1, -1], d <- [1, -1], %{ha_sign: h, dec_sign: d} != signs, do: %{ha_sign: h, dec_sign: d}

        best =
          others
          |> Enum.map(fn sg -> {sg, Model.fit(fit_samples, sg, start)} end)
          |> Enum.min_by(fn {_, {:ok, _, q}} -> q.rms_arcmin end)

        case best do
          {sg, {:ok, p, q}} when q.rms_arcmin < rms / 5 ->
            # three stars with one mis-named can look like a flipped axis:
            # the model uses the better signs either way, the global setting
            # only changes once a fourth star agrees
            if length(fit_samples) >= 4, do: Settings.put("pointing", %{"ha_sign" => sg.ha_sign, "dec_sign" => sg.dec_sign})
            {:ok, p, q, sg}

          _ ->
            {:ok, p0, q0} = first
            {:ok, p0, q0, signs}
        end

      {:ok, p, q} ->
        {:ok, p, q, signs}

      other ->
        other
    end
    |> case do
      {:ok, p, q, sg} -> {:ok, %{p | off_ra: Astro.norm180(p.off_ra)}, q, sg}
      other -> other
    end
  end

  defp put_samples(id, samples, home_at \\ :keep) do
    all = Settings.get(@key, %{})
    entry = Map.get(all, id, %{}) |> Map.put("samples", samples)
    entry = if home_at == :keep, do: entry, else: Map.put(entry, "home_at", home_at)
    Settings.put(@key, Map.put(all, id, entry))
  end

  # -- which star ------------------------------------------------------------------------------

  @doc """
  Bright stars up now, as candidates for the next sample: above 20°, not
  already used, ranked by how much they would spread the set (far from the
  stars already done, mid-altitude). Each carries plain words for where to look.
  """
  def candidates(id, %{now: now, site: site}, limit \\ 6) do
    lst = Astro.lst_deg(now, site.lon)
    horizon = Settings.horizon()
    done = samples(id)
    done_vecs = Enum.map(done, &Astro.altaz_vec(&1["alt"], &1["az"]))
    done_names = Enum.map(done, & &1["name"])

    Stars.all()
    |> Enum.filter(&(&1.kind == :star and &1.mag <= 2.2 and &1.name not in done_names))
    |> Enum.map(fn s ->
      {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, lst)
      v = Astro.altaz_vec(alt, az)
      spread = if done_vecs == [], do: 90.0, else: Enum.min(Enum.map(done_vecs, &Astro.separation(v, &1)))
      # mid-altitude stars are easy to reach and free of refraction; very high ones are awkward at a GEM
      alt_score = 1.0 - abs(alt - 50) / 50
      Map.merge(s, %{alt: alt, az: az, spread: spread, score: min(spread, 90) / 90 * 0.7 + alt_score * 0.3 - s.mag * 0.05, where: where_words(alt, az)})
    end)
    # above 20° and clear of the tree line by a margin — a star behind the
    # oaks is no use for lining up
    |> Enum.filter(&(&1.alt > 20 and &1.alt > Settings.horizon_at(horizon, &1.az) + 5))
    |> Enum.sort_by(&(-&1.score))
    |> Enum.take(limit)
  end

  @doc "The best next star, or nil when nothing bright is up."
  def next(id, ctx), do: candidates(id, ctx, 1) |> List.first()

  @doc """
  "You're probably on …": bright stars nearest to where the current model says
  the tube points, with distances. Empty until the tube points somewhere the
  model can name (homed, or at least one sample).
  """
  def guess(%{axes: axes} = snap, %{now: now, site: site} = ctx, limit \\ 3) do
    with {ra, dec} <- Pointing.scope_radec(snap, ctx) do
      lst = Astro.lst_deg(now, site.lon)
      {alt0, az0} = Astro.alt_az(ra, dec, site.lat, lst)
      v0 = Astro.altaz_vec(alt0, az0)

      Stars.all()
      |> Enum.filter(&(&1.kind == :star and &1.mag <= 2.5))
      |> Enum.map(fn s ->
        {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, lst)
        Map.merge(s, %{alt: alt, az: az, away_deg: Astro.separation(v0, Astro.altaz_vec(alt, az)), where: where_words(alt, az)})
      end)
      |> Enum.filter(&(&1.alt > 5))
      |> Enum.sort_by(& &1.away_deg)
      |> Enum.take(limit)
    else
      _ -> []
    end
    |> then(fn list -> if axes, do: list, else: [] end)
  end

  # -- words -------------------------------------------------------------------------------------

  @doc "Where to look, for a person: 'high in the east', 'low in the south-west'."
  def where_words(alt, az) do
    height =
      cond do
        alt >= 70 -> "nearly overhead"
        alt >= 45 -> "high"
        alt >= 25 -> "halfway up"
        true -> "low"
      end

    dirs = ~w(north north-east east south-east south south-west west north-west)
    dir = Enum.at(dirs, rem(round(az / 45), 8))
    if height == "nearly overhead", do: height, else: "#{height} in the #{dir}"
  end

  defp axis_words(m, lat) do
    off = Model.axis_error(m, lat)
    ideal = Model.ideal(lat)
    daz = Astro.norm180(m.axis_az - ideal.axis_az)
    dalt = m.axis_alt - ideal.axis_alt

    side =
      [
        if(abs(daz) >= 0.5, do: "#{:erlang.float_to_binary(abs(daz), decimals: 1)}° #{if daz > 0, do: "east", else: "west"} of north"),
        if(abs(dalt) >= 0.5, do: "#{:erlang.float_to_binary(abs(dalt), decimals: 1)}° too #{if dalt > 0, do: "steep", else: "shallow"}")
      ]
      |> Enum.reject(&is_nil/1)
      |> Enum.join(", ")

    cond do
      off < 0.5 -> "polar axis on the pole"
      side == "" -> "polar axis #{:erlang.float_to_binary(off, decimals: 1)}° from the pole"
      true -> "polar axis #{:erlang.float_to_binary(off, decimals: 1)}° from the pole (#{side})"
    end
  end
end
