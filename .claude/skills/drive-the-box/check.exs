# Read-only: what tonight's one-tap alignment depends on, as the box has it. Prints no coordinates.
s = Controller.Settings
p = Controller.Sky.Pointing
IO.puts("T fw=#{Nerves.Runtime.KV.get_active("nerves_fw_uuid") |> String.slice(0, 8)} clock=#{Controller.Clock.synced?()}")
site = p.site()
IO.puts("T site_set=#{p.site_set?()} name=#{inspect(site[:name])}")
IO.puts("T pointing=#{inspect(p.pointing())} offset=#{inspect(s.get("pointing_offset"))}")
IO.puts("T focal=#{inspect(s.get("focal_length_mm"))} aperture=#{inspect(s.get("aperture_mm"))} tracking_direction=#{inspect(s.get("tracking_direction"))} auto_track=#{inspect(s.get("auto_track"))}")
for {id, e} <- s.get("lineup", %{}) do
  IO.puts("T lineup #{id} n=#{length(e["samples"] || [])} signs=#{inspect(e["signs"])} corrected=#{inspect(e["signs_corrected"])} rms=#{inspect(e["rms_arcmin"])} home_at=#{inspect(e["home_at"])}")
end
IO.puts("T mounts=#{inspect(Enum.map(Mount.list(), & &1.id))}")
for m <- Mount.list() do
  snap = Mount.snapshot(m.id)
  IO.puts("T snap #{m.id} connected=#{snap.connected} homed=#{snap.homed} tracking=#{inspect(snap.tracking)} ra=#{snap.axes.ra.degrees} dec=#{snap.axes.dec.degrees} limits=#{inspect(snap[:limits])}")
end
st = Controller.StillCamera.status()
IO.puts("T still camera=#{inspect(st.camera && Map.take(st.camera, [:state, :model, :settings]))} shooting=#{st.shooting} solving=#{inspect(st[:solving])} free_mb=#{div(Controller.StillCamera.free_bytes() || 0, 1_000_000)}")
IO.puts("T scope_camera=#{inspect(Controller.ScopeCamera.status()[:camera])}")
IO.puts("T lock=#{inspect(Controller.LockOn.status().state)} plates=#{inspect(Controller.Plates.status())}")
IO.puts("T solver index=#{inspect(Path.wildcard("/data/astrometry/*") |> Enum.take(12))}")
