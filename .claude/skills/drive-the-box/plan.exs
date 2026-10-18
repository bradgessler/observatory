# An observing plan the box runs itself (a stand-in for #126), detached from the ssh session that starts it, so a
# Wi-Fi drop on the Mac's side cannot stop it halfway. Each step: Go To and Centre (flip allowed), then N good pictures
# at ISO/SHUTTER, then the next. It stops (does not move on) when the hold ends under it, and writes its progress to
# /root/.observatory/plan.json and the log. Stop it with: send(:plan_runner, :stop).
# PLAN="m76:28,m57:30,sol-saturn:40:800:1/40,sol-saturn:10:3200:10" ISO=3200 SHUTTER=15 (a step's own ISO and
# shutter after its count; a step on the same target as the one before is not centred again; planets by their
# ephemeris id; NAME@RA/DEC in J2000 degrees for anything the catalogue lacks); FIRST_SKIP_CENTRE=1 when the first target is already centred.
# a step's count is pictures ("30"), minutes of light ("90m": as many good pictures as add up to 90 minutes of
# exposure at the step's shutter speed) or hours by the clock ("2.5h": pictures for two and a half hours from when
# the step starts shooting, however many that is: how a night's windows are planned). Fewer targets, longer on
# each, is where the detail is (13 October).
count = fn n ->
  cond do
    String.ends_with?(n, "m") -> {:minutes, String.to_integer(String.trim_trailing(n, "m"))}
    String.ends_with?(n, "h") -> {:clock_s, round(elem(Float.parse(String.trim_trailing(n, "h")), 0) * 3600)}
    true -> String.to_integer(n)
  end
end
plan =
  (System.get_env("PLAN") || "m57:30")
  |> String.split(",", trim: true)
  |> Enum.map(fn s ->
    case String.split(s, ":") do
      [t, n] -> {t, count.(n), nil, nil}
      [t, n, i, sh] -> {t, count.(n), String.to_integer(i), sh}
    end
  end)

iso = String.to_integer(System.get_env("ISO") || "3200")
# DITHER=1.5 moves the telescope round a disc of 1.5 arcminutes between pictures (DITHER_EVERY=1: before every
# one), so the sensor's dust and hot pixels land on different sky and stacking averages them away
# (`Controller.Sky.Dither`; 17 October: dust shadows up to 70 arcseconds). Only for exposures of 2 s and longer: a
# planet's short frames are picked for sharpness and moving between them only costs time.
# DITHER=auto sizes the moves from the sensor map (`Controller.StillCamera.SensorMap`): past its biggest dust spot,
# none at all when the sensor is clean, small probing moves until there is a map.
dither = case System.get_env("DITHER") do nil -> nil; "auto" -> :auto; d -> elem(Float.parse(d), 0) end
dither_every = String.to_integer(System.get_env("DITHER_EVERY") || "1")
# PARK_AT=12:40 (UTC, today or the next time it comes round): the box parks the telescope itself at that time,
# whatever is running, and as soon as the plan finishes if that is sooner. 18 October 2026: the plan ended at
# 05:17, the park was left to a session that was not awake, and the telescope stood unparked into daylight.
park_at =
  case System.get_env("PARK_AT") do
    nil -> nil
    hhmm ->
      [h, m] = hhmm |> String.split(":") |> Enum.map(&String.to_integer/1)
      now = DateTime.utc_now()
      t = %{now | hour: h, minute: m, second: 0, microsecond: {0, 0}}
      if DateTime.compare(t, now) == :gt, do: t, else: DateTime.add(t, 86_400)
  end

# The park, as drive-the-box/park.exs does it: stop the plan, let the picture in flight finish, stop
# shooting, end the hold, send the mount home (counterweight down, tube at the pole), tracking off.
park = fn why ->
  require Logger
  alias Controller.StillCamera
  alias Controller.Sky.{Pointing, Tracker}
  id = "ttyUSB0"
  Logger.warning("plan: parking (#{why})")
  # ended outright, not asked: a plan in the middle of centring reads no messages, and would Go To after the park
  if (pid = Process.whereis(:plan_runner)) && pid != self(), do: Process.exit(pid, :kill)
  Controller.Sky.Centre.stop(id)
  StillCamera.continuous(false)
  idle = fn idle, k -> if StillCamera.status().busy and k > 0, do: (Process.sleep(1000); idle.(idle, k - 1)), else: :ok end
  idle.(idle, 150)
  Tracker.stop(id)
  ref = Enum.find(Mount.list(), &(&1.id == id))
  r = Pointing.home_leg(ref, Mount.snapshot(id), Pointing.context(DateTime.utc_now(), id))
  Logger.warning("plan: park #{inspect(r) |> String.slice(0, 120)}")
  File.write("/root/.observatory/plan.json", Jason.encode!(%{phase: :parked, why: why, result: inspect(r), at: DateTime.utc_now()}))
end

if old = Process.whereis(:park_timer), do: Process.exit(old, :kill)

if park_at do
  spawn(fn ->
    Process.register(self(), :park_timer)
    Process.sleep(max(DateTime.diff(park_at, DateTime.utc_now(), :millisecond), 0))
    park.("PARK_AT #{Calendar.strftime(park_at, "%H:%M")}Z")
  end)
end
shutter = System.get_env("SHUTTER") || "15"
skip_first = System.get_env("FIRST_SKIP_CENTRE") == "1"

if pid = Process.whereis(:plan_runner), do: Process.exit(pid, :kill)

runner = fn ->
  alias Controller.StillCamera
  alias Controller.Sky.{Centre, Catalog, Tracker}
  require Logger
  Process.register(self(), :plan_runner)
  # a run of pictures left going (13 October: the camera was still on M33) answers every centring picture :busy,
  # and each target is then skipped as "not centred". The plan owns the camera from here.
  StillCamera.continuous(false)
  id = "ttyUSB0"
  # and a centring left running by a plan this one replaces would fight this one's first Go To
  Centre.stop(id)
  file = "/root/.observatory/plan.json"
  progress = fn map -> File.write(file, Jason.encode!(Map.put(map, :at, DateTime.utc_now()))) end
  say = fn words -> Logger.warning("plan: " <> words) end

  stopped? = fn -> receive do :stop -> true after 0 -> false end end

  centre = fn obj ->
    # the centring pictures are taken with whatever the camera is set to, and a step may have left it at 1/60 s
    # (13 October: after Almach every centring picture was black and NGC 891 was skipped). Set what a solve needs.
    StillCamera.set(iso: 6400, shutter: "2")
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
    # minutes of light become pictures at this step's shutter speed
    {n, until} =
      case n do
        {:clock_s, secs} -> {1_000_000, System.monotonic_time(:second) + secs}
        {:minutes, m} ->
          secs = case String.split(to_string(shutter), "/") do [a, b] -> String.to_integer(a) / String.to_integer(b); [a] -> elem(Float.parse(a), 0) end
          {max(ceil(m * 60 / secs), 1), nil}
        n -> {n, nil}
      end
    say.("#{name}: waiting for the hold to settle: #{inspect(steady.(steady, 0, 60))}")
    StillCamera.set(iso: iso, shutter: shutter)
    start = StillCamera.status().good
    exposure_s = case String.split(to_string(shutter), "/") do [a, b] -> String.to_integer(a) / String.to_integer(b); [a] -> elem(Float.parse(a), 0) end
    StillCamera.continuous(true, 0, if(dither && exposure_s >= 2, do: [dither: dither, dither_every: dither_every], else: []))
    watch = fn watch ->
      s = StillCamera.status()
      done = s.good - start
      progress.(%{target: name, phase: :shooting, good: done, of: if(until, do: "until the step's time is up", else: n), last: s.last && Path.basename(s.last.base)})
      cond do
        done >= n -> :done
        is_integer(until) and System.monotonic_time(:second) >= until -> :done
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
  # nothing left to shoot: park now rather than wait for the timer (the timer is then not needed)
  if park_at do
    if t = Process.whereis(:park_timer), do: Process.exit(t, :kill)
    park.("the plan finished")
  end
end

pid = spawn(runner)
IO.puts("S plan runner #{inspect(pid)}: #{inspect(plan)} at ISO #{iso}, #{shutter} s; park #{if park_at, do: "at #{Calendar.strftime(park_at, "%H:%M")}Z or when done", else: "NOT armed (set PARK_AT)"}")
