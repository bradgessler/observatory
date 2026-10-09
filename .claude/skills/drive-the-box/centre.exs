alias Controller.Sky.{Centre, Lineup, Stars, Catalog, Tracker}
id = "ttyUSB0"
name = System.get_env("TARGET") || "m57"
obj = Enum.find(Stars.all(), &(&1.name == name)) || Enum.find(Catalog.dsos(), &(&1.id == name))
ls = Lineup.status(id)
IO.puts("S lineup n=#{ls.n} rms=#{inspect(ls.rms_arcmin)} cw=#{inspect(Lineup.counterweight(id))} homed=#{Mount.snapshot(id).homed}")
t0 = System.monotonic_time(:second)
IO.puts("S start #{obj.name}: #{inspect(Centre.start(id, obj))}")
loop = fn loop, last ->
  st = Centre.status(id)
  if st != last and st, do: IO.puts("S +#{System.monotonic_time(:second) - t0}s #{st.phase} try #{st.tries} off #{inspect(st.off_arcmin && Float.round(st.off_arcmin, 1))}′ · #{st.words}")
  cond do
    st && st.done -> st
    System.monotonic_time(:second) - t0 > 300 -> IO.puts("S still running after 5 min"); st
    true -> Process.sleep(500); loop.(loop, st)
  end
end
loop.(loop, nil)
Process.sleep(3000)
t = Tracker.status(id)
IO.puts("S hold #{inspect(t && Map.take(t, [:name, :ra_rate, :dec_rate, :error_arcmin, :paused]))} stalled=#{inspect(Mount.snapshot(id)[:stalled])}")
IO.puts("S last picture #{Controller.StillCamera.status().last.base |> Path.basename()}")
