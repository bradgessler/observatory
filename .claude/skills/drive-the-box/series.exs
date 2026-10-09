# Go To and Centre on TARGET, then N pictures at ISO / SHUTTER back to back, then back to the finder exposure.
# TARGET is a catalogue id (m57) or a star's name; N (30), ISO (3200), SHUTTER ("15").
alias Controller.StillCamera
alias Controller.Sky.{Centre, Catalog, Stars, Tracker}
id = "ttyUSB0"
name = System.get_env("TARGET") || "m57"
n = String.to_integer(System.get_env("N") || "30")
iso = String.to_integer(System.get_env("ISO") || "3200")
shutter = System.get_env("SHUTTER") || "15"
obj = Enum.find(Catalog.dsos(), &(&1.id == name)) || Enum.find(Stars.all(), &(&1.name == name))
t0 = System.monotonic_time(:second)
el = fn -> System.monotonic_time(:second) - t0 end
IO.puts("S centre #{obj.name}: #{inspect(Centre.start(id, obj, Keyword.new(if(System.get_env("FLIP") == "1", do: [flip: true], else: []))))}")
loop = fn loop, last ->
  st = Centre.status(id)
  if st != last and st, do: IO.puts("S +#{el.()}s #{st.phase} try #{st.tries} off #{inspect(st.off_arcmin && Float.round(st.off_arcmin, 2))}′ · #{st.words}")
  if (st && st.done) or el.() > 300, do: st, else: (Process.sleep(500); loop.(loop, st))
end
st = loop.(loop, nil)
if st && st.ok do
  IO.puts("S set #{inspect(StillCamera.set(iso: iso, shutter: shutter) |> elem(0))} iso #{iso} shutter #{shutter}")
  start_good = StillCamera.status().good
  start_seq = (StillCamera.status().last || %{})[:seq] || 0
  :ok = StillCamera.continuous(true)
  watch = fn watch, seen ->
    s = StillCamera.status()
    last = s.last || %{}
    seen = if (last[:seq] || 0) > seen and not s.busy, do: (IO.puts("S +#{el.()}s #{Path.basename(last.base)} stars=#{last.stars} size=#{inspect(last.star_size && last.star_size.arcsec)} bg=#{last.background} cloud=#{inspect(last[:cloud])} settling=#{inspect(last[:settling])} good=#{s.good - start_good}/#{n}"); last.seq), else: seen
    cond do
      s.good - start_good >= n -> :done
      not s.shooting -> IO.puts("S shooting stopped: #{inspect(s[:why])}"); :stopped
      Tracker.status(id) == nil -> IO.puts("S the hold ended: #{inspect(Tracker.ended(id))}"); :no_hold
      el.() > 3600 -> :timeout
      true -> Process.sleep(1000); watch.(watch, seen)
    end
  end
  r = watch.(watch, start_seq)
  StillCamera.continuous(false)
  IO.puts("S series #{r}: #{StillCamera.status().good - start_good} good pictures in #{el.()} s")
  StillCamera.set(iso: 6400, shutter: "2")
end
