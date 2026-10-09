# An observing plan the box runs itself (a stand-in for #126), detached from the ssh session that starts it, so a
# Wi-Fi drop on the Mac's side cannot stop it halfway. Each step: Go To and Centre (flip allowed), then N good pictures
# at ISO/SHUTTER, then the next. It stops (does not move on) when the hold ends under it, and writes its progress to
# /root/.observatory/plan.json and the log. Stop it with: send(:plan_runner, :stop).
# PLAN="m76:28,m57:30,m27:30,m31:30" ISO=3200 SHUTTER=15; FIRST_SKIP_CENTRE=1 when the first target is already centred.
plan =
  (System.get_env("PLAN") || "m57:30")
  |> String.split(",", trim: true)
  |> Enum.map(fn s -> [t, n] = String.split(s, ":"); {t, String.to_integer(n)} end)

iso = String.to_integer(System.get_env("ISO") || "3200")
shutter = System.get_env("SHUTTER") || "15"
skip_first = System.get_env("FIRST_SKIP_CENTRE") == "1"

if pid = Process.whereis(:plan_runner), do: Process.exit(pid, :kill)

runner = fn ->
  alias Controller.StillCamera
  alias Controller.Sky.{Centre, Catalog, Tracker}
  require Logger
  Process.register(self(), :plan_runner)
  id = "ttyUSB0"
  file = "/root/.observatory/plan.json"
  progress = fn map -> File.write(file, Jason.encode!(Map.put(map, :at, DateTime.utc_now()))) end
  say = fn words -> Logger.warning("plan: " <> words) end

  stopped? = fn -> receive do :stop -> true after 0 -> false end end

  centre = fn obj ->
    Centre.start(id, obj, flip: true)
    wait = fn wait, n ->
      st = Centre.status(id)
      cond do
        st && st.done -> st
        n <= 0 -> st
        true -> Process.sleep(1000); wait.(wait, n - 1)
      end
    end
    wait.(wait, 600)
  end

  shoot = fn name, n ->
    StillCamera.set(iso: iso, shutter: shutter)
    start = StillCamera.status().good
    StillCamera.continuous(true)
    watch = fn watch ->
      s = StillCamera.status()
      done = s.good - start
      progress.(%{target: name, phase: :shooting, good: done, of: n, last: s.last && Path.basename(s.last.base)})
      cond do
        done >= n -> :done
        not s.shooting -> {:stopped, s[:why]}
        Tracker.status(id) == nil -> {:no_hold, Tracker.ended(id)}
        stopped?.() -> :asked
        true -> Process.sleep(2000); watch.(watch)
      end
    end
    r = watch.(watch)
    StillCamera.continuous(false)
    r
  end

  Enum.reduce_while(Enum.with_index(plan), :ok, fn {{tid, n}, i}, _ ->
    obj = Enum.find(Catalog.dsos(), &(&1.id == tid))
    say.("#{obj.name}: #{if i == 0 and skip_first, do: "already centred", else: "Go To and Centre"}")
    st = if i == 0 and skip_first, do: %{ok: true}, else: centre.(obj)
    progress.(%{target: obj.name, phase: :centred, centre: st && Map.take(st, [:ok, :tries, :off_arcmin, :words])})

    if st && st.ok do
      r = shoot.(obj.name, n)
      say.("#{obj.name}: #{inspect(r)}")
      progress.(%{target: obj.name, phase: :shot, result: inspect(r)})
      if r == :done, do: {:cont, :ok}, else: {:halt, r}
    else
      say.("#{obj.name}: not centred (#{inspect(st && st[:words])}), skipping")
      {:cont, :skipped}
    end
  end)

  StillCamera.continuous(false)
  StillCamera.set(iso: 6400, shutter: "2")
  progress.(%{phase: :finished})
  say.("finished")
end

pid = spawn(runner)
IO.puts("S plan runner #{inspect(pid)}: #{inspect(plan)} at ISO #{iso}, #{shutter} s")
