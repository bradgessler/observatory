# One picture at the camera's current settings; the star size to focus by. Run again after each turn of the knob.
alias Controller.StillCamera
before = (StillCamera.status().last || %{})[:seq] || 0
StillCamera.shoot()
wait = fn wait, n -> st = StillCamera.status(); if (st.last[:seq] || 0) > before and not st.busy, do: st.last, else: (if n > 0, do: (Process.sleep(300); wait.(wait, n - 1)), else: st.last) end
last = wait.(wait, 300)
was = Process.get(:was)
size = last.star_size
IO.puts("S #{Path.basename(last.base)} star size #{inspect(size && size.arcsec)}\" (#{inspect(size && size.n)} stars, half-flux diameter) bg=#{last.background} max=#{last.max} stars=#{last.stars}#{if is_map(last[:star_size_was]), do: " · was #{inspect(last.star_size_was[:arcsec])}\"", else: ""}")
