# An observing plan the box runs itself (a stand-in for #126), detached from the ssh session that starts it, so a
# Wi-Fi drop on the Mac's side cannot stop it halfway. Each step: Go To and Centre (flip allowed), then N good pictures
# at ISO/SHUTTER, then the next. It stops (does not move on) when the hold ends under it, and writes its progress to
# /root/.observatory/plan.json and the log. Stop it with: send(:plan_runner, :stop).
# PLAN="m76:28,m57:30,sol-saturn:40:800:1/40,sol-saturn:10:3200:10" ISO=3200 SHUTTER=15 (a step's own ISO and
# shutter after its count; a step on the same target as the one before is not centred again; planets by their
# ephemeris id; NAME@RA/DEC in J2000 degrees for anything the catalogue lacks); FIRST_SKIP_CENTRE=1 when the first target is already centred.
plan =
  (System.get_env("PLAN") || "m57:30")
  |> String.split(",", trim: true)
  |> Enum.map(fn s ->
    case String.split(s, ":") do
      [t, n] -> {t, String.to_integer(n), nil, nil}
      [t, n, i, sh] -> {t, String.to_integer(n), String.to_integer(i), sh}
    end
  end)

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

  # the camera finishing a picture answers every finder :busy (8 Oct: the Dumbbell's centring gave up on it)
  idle = fn idle, k -> if StillCamera.status().busy and k > 0, do: (Process.sleep(1000); idle.(idle, k - 1)), else: :ok end

  # NAME@RA/DEC (J2000 degrees) for anything the catalogue doesn't carry
  find = fn tid ->
    case String.split(tid, "@") do
      [name, coords] ->
        [ra, dec] = coords |> String.split("/") |> Enum.map(&elem(Float.parse(&1), 0))
        %{id: name, name: name, ra_deg: ra, dec_deg: dec}

      _ -> nil
    end ||
    Enum.find(Catalog.dsos(), &(&1.id == tid)) ||
      Enum.find(Controller.Sky.Ephemeris.objects(DateTime.utc_now(), Controller.Sky.Pointing.site()), &(&1.id == tid))
  end

  # The hold takes up what is left after a Go To or a nudge over ~20 s, faster than tracking: pictures taken then are
  # smeared (8 Oct, the Crystal Ball's first frames at 12.7"). Wait until it has been steady for a few seconds.
  steady = fn steady, ok, k ->
    t = Tracker.status(id)
    good = is_map(t) and t.paused == false and is_number(t.error_arcmin) and t.error_arcmin < 0.15
    cond do
      ok >= 4 -> :steady
      k <= 0 -> :timeout
      true -> Process.sleep(1000); steady.(steady, if(good, do: ok + 1, else: 0), k - 1)
    end
  end

  shoot = fn name, n, iso, shutter ->
    say.("#{name}: waiting for the hold to settle: #{inspect(steady.(steady, 0, 60))}")
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

  Enum.reduce_while(Enum.with_index(plan), :ok, fn {{tid, n, step_iso, step_shutter}, i}, _ ->
    obj = find.(tid)
    again = i > 0 and elem(Enum.at(plan, i - 1), 0) == tid
    say.("#{obj.name}: #{cond do i == 0 and skip_first -> "already centred"; again -> "same target"; true -> "Go To and Centre" end}")
    idle.(idle, 90)
    st = if (i == 0 and skip_first) or again, do: %{ok: true}, else: centre.(obj)
    progress.(%{target: obj.name, phase: :centred, centre: st && Map.take(st, [:ok, :tries, :off_arcmin, :words])})

    if st && st.ok do
      r = shoot.(obj.name, n, step_iso || iso, step_shutter || shutter)
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
