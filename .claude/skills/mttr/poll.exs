lo = Controller.LockOn.status(); st = Controller.StillCamera.status()
m = try do Mount.snapshot(lo[:mount] || "ttyUSB0") catch _, _ -> nil end
IO.puts("P lock #{lo.state}#{if lo[:error_px], do: " err #{inspect(lo.error_px)}", else: ""} | #{lo[:why]} | mount #{inspect(m && m[:connected])} | clock #{Controller.Clock.synced?()} | camera #{inspect(st.camera && st.camera.state)} shooting #{st.shooting} last #{inspect(st.last && {st.last.seq, Calendar.strftime(st.last.at, "%H:%M:%S")})}")
