# Read only, moves nothing. Before a plan starts: each step of PLAN (the same string plan.exs takes) at the time
# its turn would come if the plan started now, its altitude and hour angle at the start and end of its turn, the
# pose a Go To would land in, and whether the hold would reach its meridian limit (+20 degrees of counterweight,
# about 1.3 h past the meridian) before the step ends, which stops the whole plan. Then PARK_AT and the Sun.
#
#   PLAN='m27:0.6h,m33:1h,sol-saturn:2h:800:1/60,m42:2.7h:1600:30' PARK_AT=12:40 ISO=3200 SHUTTER=15 box - < plan_check.exs
#
# 17 October 2026: the night's own check had its plan typed in and was hand-edited twice when the plan changed.
alias Controller.Sky.{Astro, Catalog, Ephemeris, Pointing}
id = "ttyUSB0"
site = Pointing.site()
snap = Mount.snapshot(id)
shutter_default = System.get_env("SHUTTER") || "15"
secs = fn sh -> case String.split(to_string(sh), "/") do [a, b] -> String.to_integer(a) / String.to_integer(b); [a] -> elem(Float.parse(a), 0) end end
# a picture takes its exposure plus about 20 s around it (download, the next press, a dither now and then)
per_picture = fn sh -> secs.(sh) + 20 end
goto_s = 180

steps =
  (System.get_env("PLAN") || "")
  |> String.split(",", trim: true)
  |> Enum.map(fn s ->
    {t, n, sh} =
      case String.split(s, ":") do
        [t, n] -> {t, n, shutter_default}
        [t, n, _iso, sh] -> {t, n, sh}
      end

    dur =
      cond do
        String.ends_with?(n, "h") -> round(elem(Float.parse(String.trim_trailing(n, "h")), 0) * 3600)
        String.ends_with?(n, "m") -> round(String.to_integer(String.trim_trailing(n, "m")) * 60 / secs.(sh) * per_picture.(sh))
        true -> round(String.to_integer(n) * per_picture.(sh))
      end

    {t, dur}
  end)

find = fn tid, at ->
  case String.split(tid, "@") do
    [name, coords] ->
      [ra, dec] = coords |> String.split("/") |> Enum.map(&elem(Float.parse(&1), 0))
      %{id: name, name: name, ra_deg: ra, dec_deg: dec}

    _ ->
      Enum.find(Catalog.dsos(), &(to_string(&1.id) == tid)) || Enum.find(Ephemeris.objects(at, site), &(&1.id == tid))
  end
end

hhmm = fn t -> t |> DateTime.to_time() |> to_string() |> String.slice(0, 5) end

{ends, _prev} =
  Enum.reduce(steps, {DateTime.utc_now(), nil}, fn {tid, dur}, {t, prev} ->
    # a step on the same target as the one before is not centred again
    start = if tid == prev, do: t, else: DateTime.add(t, goto_s)
    stop = DateTime.add(start, dur)

    case find.(tid, start) do
      nil ->
        IO.puts("W #{tid}: not in the catalogue (use NAME@RA/DEC)")

      obj ->
        line =
          for at <- [start, stop] do
            lst = Astro.lst_deg(at, site.lon)
            {alt, _az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, site.lat, lst)
            {round(alt), Float.round(Astro.norm180(lst - obj.ra_deg) / 15, 2)}
          end

        [{a0, h0}, {a1, h1}] = line
        land = Pointing.landing(obj, snap, Pointing.context(start, id))
        # the hold stops at +20 degrees of counterweight, about 1.3 h past the meridian, for a target taken east of
        # the meridian that crosses it (one already west at its Go To is taken flipped and is fine)
        past = if h0 < 0.25 and h1 > 1.25, do: " HOLD ENDS BEFORE THIS STEP DOES (#{h1} h past the meridian): shorten it or the plan stops", else: ""
        low = if min(a0, a1) < 30, do: " LOW (#{min(a0, a1)} degrees)", else: ""
        IO.puts("W #{String.pad_trailing(tid, 10)} #{hhmm.(start)}Z alt #{a0} HA #{h0}h -> #{hhmm.(stop)}Z alt #{a1} HA #{h1}h | pose=#{inspect(land[:pose])} cw=#{land[:cw] && Float.round(land.cw, 1)}#{past}#{low}")
    end

    {stop, tid}
  end)

IO.puts("W the plan would end about #{hhmm.(ends)}Z")

case System.get_env("PARK_AT") do
  nil ->
    IO.puts("W PARK_AT not set: the telescope will not park itself. Set it (18 October: nothing parked it)")

  park ->
    [h, m] = park |> String.split(":") |> Enum.map(&String.to_integer/1)
    now = DateTime.utc_now()
    t = %{now | hour: h, minute: m, second: 0, microsecond: {0, 0}}
    t = if DateTime.compare(t, now) == :gt, do: t, else: DateTime.add(t, 86_400)
    sun = Float.round(Ephemeris.sun_alt(t, site), 1)
    order = if DateTime.compare(ends, t) == :gt, do: "the park cuts the plan short", else: "the plan finishes first and parks then"
    IO.puts("W park at #{hhmm.(t)}Z, Sun #{sun} degrees #{if sun > -12, do: "(TOO LATE: the sky is already light)", else: ""}; #{order}")
end
