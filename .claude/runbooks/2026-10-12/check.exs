alias Controller.Sky.{Astro, Catalog, Pointing, Lineup}
id = "ttyUSB0"
site = Pointing.site(); horizon = Controller.Settings.horizon(); all = Catalog.dsos()
snap = Mount.snapshot(id)
# Read only. Each target of tonight's plan at the time its turn would come if the plan started now: altitude, hour
# angle (negative: east of the meridian), and the pose a Go To would land in. Every pose must be :same (no meridian
# flip) and every cw_after below 20 before the plan is started.
t0 = DateTime.utc_now()
at = fn mins -> DateTime.add(t0, mins * 60) end
# {id, ra, dec, minutes after the start, minutes it takes}
plan = [
  {"Almach", 30.975, 42.330, at.(0), 6},
  {"NGC891", 35.639, 42.349, at.(6), 24},
  {"m77", nil, nil, at.(30), 24},
  {"NGC1535", 63.566, -12.739, at.(54), 14},
  {"m1", nil, nil, at.(68), 30},
  {"m78", nil, nil, at.(98), 26},
  {"NGC2261", 99.791, 8.738, at.(124), 22},
  {"NGC2392", 112.295, 20.912, at.(146), 14},
  {"NGC2419", 114.535, 38.882, at.(160), 22},
  {"m82", nil, nil, at.(182), 30}
]
for {name, ra, dec, at, mins} <- plan do
  obj = Enum.find(all, &(to_string(&1.id) == name)) || %{id: name, name: name, ra_deg: ra, dec_deg: dec}
  line = for t <- [at, DateTime.add(at, mins * 60)] do
    lst = Astro.lst_deg(t, site.lon)
    {alt, az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, site.lat, lst)
    "#{t |> DateTime.to_time() |> to_string() |> String.slice(0, 5)}Z alt #{round(alt)} tree #{Controller.Settings.horizon_at(horizon, az)} HA #{Float.round(Astro.norm180(lst - obj.ra_deg) / 15, 2)}h"
  end
  land = Pointing.landing(obj, snap, Pointing.context(at, id))
  IO.puts("W #{String.pad_trailing(name, 8)} #{Enum.join(line, " -> ")} | at its start: pose=#{inspect(land[:pose])} cw_after=#{land[:cw] && Float.round(land.cw, 1)}")
end
m = Lineup.model(id); st = Lineup.status(id)
IO.puts("W now: cw=#{Float.round(Controller.Sky.Model.counterweight(m, m.signs, snap.axes.ra.degrees), 1)} told=#{inspect(m[:cw_told])} side=#{inspect(st[:counterweight])} hard_limit=#{inspect(Pointing.meridian_hard())} n=#{st.n} rms=#{inspect(st[:rms_arcmin])} homed=#{snap.homed}")
IO.puts("W the plan would end about #{at.(212) |> DateTime.to_time() |> to_string() |> String.slice(0, 5)}Z; park by 12:25Z whatever is running")
IO.puts("W sun alt at 12:30Z #{Float.round(Controller.Sky.Ephemeris.sun_alt(~U[2026-10-13 12:30:00Z], site), 1)}, 12:45Z #{Float.round(Controller.Sky.Ephemeris.sun_alt(~U[2026-10-13 12:45:00Z], site), 1)}")
