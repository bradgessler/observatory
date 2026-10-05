# What the box is doing right before it goes down: this is what it must come back to.
lo = Controller.LockOn.status(); st = Controller.StillCamera.status()
hb = Controller.Settings.get("lock_on_resume")
moving = Mount.local_list() |> Enum.any?(fn m -> Mount.snapshot(m.id).axes |> Map.values() |> Enum.any?(&(&1[:goto_pending] == true or (&1.running and abs(&1.deg_per_s || 0) > 0.01))) end)
aligning = Mount.list() |> Enum.any?(fn m -> match?(%{done: false}, Controller.AutoAlign.status(m.id)) end)
age = with %{"at" => at} <- hb, {:ok, t, _} <- DateTime.from_iso8601(at), do: DateTime.diff(DateTime.utc_now(), t), else: (_ -> nil)
IO.puts("B lock=#{lo.state} error=#{inspect(lo[:error_px])} heartbeat_age_s=#{inspect(age)} shooting=#{st.shooting} busy=#{moving or aligning} fw=#{Nerves.Runtime.KV.get_active("nerves_fw_uuid") |> String.slice(0, 8)}")
