# End of the night, before the Sun: stop the plan, let the picture in flight finish, stop shooting, end the hold and
# send the mount home (counterweight straight down, tube at the pole). The pole is in the north, and the Sun never
# comes within 60 degrees of it, so a tube left there is safe all day. Tracking is off afterwards: nothing follows
# the sky round to the east. With the counterweight's side not told it moves nothing (home could be upside down):
# it stops everything, says so, and the tube stays where it is, which Brad then has to cover or turn by hand.
alias Controller.StillCamera
alias Controller.Sky.{Pointing, Tracker}
id = "ttyUSB0"

if pid = Process.whereis(:plan_runner), do: send(pid, :stop)
StillCamera.continuous(false)
idle = fn idle, k -> if StillCamera.status().busy and k > 0, do: (Process.sleep(1000); idle.(idle, k - 1)), else: :ok end
idle.(idle, 150)
IO.puts("S camera idle=#{not StillCamera.status().busy} shooting=#{StillCamera.status()[:shooting]}")

Tracker.stop(id)
ref = Enum.find(Mount.list(), &(&1.id == id))
snap = Mount.snapshot(id)
ctx = Pointing.context(DateTime.utc_now(), id)

case Pointing.home_leg(ref, snap, ctx) do
  {:error, why} ->
    IO.puts("S NOT PARKED: #{inspect(why)}. Both motors are stopped and tracking is off; the tube is where it was.")

  other ->
    IO.puts("S going home: #{inspect(other) |> String.slice(0, 120)}")
    Process.sleep(1500)
    wait = fn wait, k ->
      s = Mount.snapshot(id)
      moving = Enum.any?([:ra, :dec], &(s.axes[&1].running or s.axes[&1][:goto_pending]))
      if moving and k > 0, do: (Process.sleep(500); wait.(wait, k - 1)), else: s
    end
    wait.(wait, 600)
end

s = Mount.snapshot(id)
dec = case Pointing.scope_radec(s, Pointing.context(DateTime.utc_now(), id)) do
  {_ra, dec} -> Float.round(dec, 1)
  _ -> nil
end
IO.puts("S parked: ra_running=#{s.axes.ra.running} dec_running=#{s.axes.dec.running} tracking=#{inspect(s[:tracking])} hold=#{inspect(Tracker.status(id))} tube_dec=#{inspect(dec)} (90 is the pole)")
