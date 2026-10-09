alias Controller.AutoAlign
alias Controller.Sky.{Astro, Lineup, Pointing}
id = "ttyUSB0"
IO.puts("S start #{inspect(AutoAlign.start(id))} at #{Calendar.strftime(DateTime.utc_now(), "%H:%M:%S")}")
t0 = System.monotonic_time(:second)
site = Pointing.site()
loop = fn loop, last, seen ->
  st = AutoAlign.status(id)
  if st != last, do: IO.puts("S +#{System.monotonic_time(:second) - t0}s #{st.phase} #{st.solved}/#{st.enough} · #{st.words}")
  plates = Controller.Plates.view(id).plates
  seen = Enum.reduce(plates, seen, fn p, acc ->
    if p.state in [:solved, :failed] and not MapSet.member?(acc, p.n) do
      case p do
        %{state: :solved, solution: %{ra_deg: ra, dec_deg: dec} = s} ->
          {alt, az} = Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(DateTime.utc_now(), site.lon))
          IO.puts("S   plate #{p.n}: enc ra=#{p.enc.ra_deg} dec=#{p.enc.dec_deg} -> RA #{Float.round(ra, 3)} Dec #{Float.round(dec, 3)} (alt #{Float.round(alt, 1)} az #{Float.round(az, 1)}) #{s.stars} stars #{s.seconds}s")
        _ -> IO.puts("S   plate #{p.n}: #{p.state} #{p.reason}")
      end
      MapSet.put(acc, p.n)
    else
      acc
    end
  end)
  cond do
    st && st.done -> st
    System.monotonic_time(:second) - t0 > 600 -> IO.puts("S still running after 10 min"); st
    true -> Process.sleep(1_000); loop.(loop, st, seen)
  end
end
st = loop.(loop, nil, MapSet.new())
ls = Lineup.status(id)
IO.puts("S lineup n=#{ls.n} rms=#{inspect(ls.rms_arcmin)} good_for=#{inspect(ls.good_for)} axis_off=#{inspect(ls.axis_off_deg)} cw=#{inspect(ls.counterweight)}")
IO.puts("S words #{inspect(ls.axis_words)}")
m = Lineup.model(id)
IO.puts("S model #{inspect(m && Map.drop(m, [:signs]))}")
