alias Controller.StillCamera
alias Controller.Sky.{Astro, Lineup, Pointing, Stars, Catalog, Tracker}
id = "ttyUSB0"
name = System.get_env("TARGET") || "Albireo"
obj = Enum.find(Stars.all(), &(&1.name == name)) || Enum.find(Catalog.dsos(), &(&1.id == name))
ref = Enum.find(Mount.list(), &(&1.id == id))
snap = Mount.snapshot(id)
ctx = Pointing.context(DateTime.utc_now(), id)
plan = Pointing.landing(obj, snap, ctx)
IO.puts("S #{obj.name} plan pose=#{plan.pose} d_ra=#{Float.round(plan.d_ra, 1)} d_dec=#{Float.round(plan.d_dec, 1)} cw_after=#{Float.round(plan.cw, 1)} told=#{Lineup.model(id)[:cw_told]}")
if plan.pose != :same or not Lineup.model(id)[:cw_told] do
  IO.puts("S not moving: pose #{plan.pose}, told #{Lineup.model(id)[:cw_told]}")
else
  t0 = System.monotonic_time(:millisecond)
  IO.puts("S slew #{inspect(Pointing.slew(ref, snap, obj, ctx, track: true))}")
  Process.sleep(1500)
  wait = fn wait -> s = Mount.snapshot(id); if s.axes.ra.goto_pending or s.axes.dec.goto_pending, do: (Process.sleep(250); wait.(wait)), else: s end
  s = wait.(wait)
  IO.puts("S landed in #{div(System.monotonic_time(:millisecond) - t0, 1000)} s: enc ra=#{s.axes.ra.degrees} dec=#{s.axes.dec.degrees} cw=#{inspect(Lineup.counterweight(id))} tracker=#{inspect(Tracker.status(id) && Map.take(Tracker.status(id), [:name, :ra_rate, :dec_rate, :error_arcmin, :paused]))}")
  Process.sleep(2500)
  r = StillCamera.finder(mount: id, scale: StillCamera.field_scale(), min_stars: 6, deadline: 60_000)
  case r do
    {:ok, %{from: :solve, ra_deg: ra, dec_deg: dec} = sol} ->
      off = Astro.separation_radec(ra, dec, obj.ra_deg, obj.dec_deg) * 60
      dra = Astro.norm180(ra - obj.ra_deg) * :math.cos(obj.dec_deg * :math.pi() / 180) * 60
      ddec = (dec - obj.dec_deg) * 60
      IO.puts("S solved #{sol.stars} stars in #{sol.seconds} s: off #{Float.round(off, 1)}′ (RA #{Float.round(dra, 1)}′, Dec #{Float.round(ddec, 1)}′) field #{Float.round(sol.width_deg * 60, 1)}′ wide")
    other -> IO.puts("S finder #{inspect(other)}")
  end
  st = StillCamera.status().last
  IO.puts("S picture #{st.base |> Path.basename()} stars=#{st.stars} size=#{inspect(st.star_size && st.star_size.arcsec)}")
end
