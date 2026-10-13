# Read only. One screen of where the night stands: the plan, the camera, the hold, and anything in the log that
# means trouble. Run it every few minutes; it moves nothing.
safe = fn f -> try do f.() rescue e -> "?#{Exception.message(e) |> String.slice(0, 60)}" catch _, _ -> "?" end end
id = "ttyUSB0"
now = DateTime.utc_now()
IO.puts("N time #{now |> DateTime.to_time() |> Time.truncate(:second)}Z fw #{safe.(fn -> Nerves.Runtime.KV.get_active("nerves_fw_uuid") |> String.slice(0, 8) end)} clock_set #{safe.(fn -> Controller.Clock.set?() end)}")
plan = safe.(fn -> File.read!("/root/.observatory/plan.json") |> Jason.decode!() end)
IO.puts("N plan runner_alive #{Process.whereis(:plan_runner) != nil} last #{inspect(plan, limit: 20) |> String.slice(0, 260)}")
st = safe.(fn -> Controller.StillCamera.status() end)
if is_map(st) do
  last = st[:last] || %{}
  IO.puts("N camera state #{inspect(st[:camera] && st.camera[:state])} shooting #{st[:shooting]} busy #{st[:busy]} good #{st[:good]} settings #{inspect(st[:camera] && Map.take(st.camera[:settings] || %{}, [:iso, :shutter]))} why #{inspect(st[:why])}")
  IO.puts("N last picture #{last[:base] && Path.basename(last.base)} at #{last[:at] && (last.at |> DateTime.to_time() |> Time.truncate(:second))}Z stars #{inspect(last[:stars])} star_size #{inspect(last[:star_size] && Float.round(last.star_size.arcsec / 1, 1))} free_mb #{safe.(fn -> div(Controller.StillCamera.free_bytes(), 1_000_000) end)}")
end
tr = safe.(fn -> Controller.Sky.Tracker.status(id) end)
IO.puts("N hold #{inspect(is_map(tr) && Map.take(tr, [:name, :paused]))} error_arcmin #{inspect(is_map(tr) && tr[:error_arcmin] && Float.round(tr.error_arcmin, 2))} cw #{inspect(is_map(tr) && tr[:cw] && Float.round(tr.cw, 1))} (hold ends at +20) ended #{inspect(safe.(fn -> Controller.Sky.Tracker.ended(id) end))}")
snap = safe.(fn -> Mount.snapshot(id) end)
if is_map(snap), do: IO.puts("N mount connected #{snap.connected} ra_running #{snap.axes.ra.running} dec_running #{snap.axes.dec.running} stalled #{inspect(snap[:stalled])}")
bad = safe.(fn ->
  Telescope.Events.recent(400)
  |> Enum.filter(&(&1.name in [:late, :hold_expired, :stall, :link_lost, :goto_failed, :limit_stop, :end] and DateTime.diff(now, &1.at) < 600))
  |> Enum.map(&"#{&1.at |> DateTime.to_time() |> Time.truncate(:second)}Z #{&1.module} #{&1.name} #{inspect(&1.data, limit: 8) |> String.slice(0, 110)}")
end)
IO.puts("N trouble in the last 10 min: #{if bad == [], do: "none", else: ""}")
if is_list(bad), do: Enum.each(bad, &IO.puts("N   " <> &1))
