# Twilight flats at dawn, with the telescope parked and nothing moving: blank sky lit evenly, tracking off, the
# exposure walked so the sky sits mid-scale, 24 frames. The camera only: this script never touches the mount, and it
# refuses to start if an axis is running or a hold is on. It runs on the box by itself (so the ssh session ending
# does not stop it), waits for the Sun to reach 9.5 degrees below the horizon, and stops at half a degree below (FLATS_UNTIL) or after 24
# good frames, whichever comes first. Progress is in the log ("flats: ..."). Stop it with send(:flats_runner, :stop).
# The frames land in the night's folder like any others, at ISO 100, pointing at the pole.
alias Controller.StillCamera
if pid = Process.whereis(:flats_runner), do: Process.exit(pid, :kill)

runner = fn ->
  require Logger
  Process.register(self(), :flats_runner)
  id = "ttyUSB0"
  say = fn words -> Logger.warning("flats: " <> words) end
  site = Controller.Sky.Pointing.site()
  sun = fn -> Controller.Sky.Ephemeris.sun_alt(DateTime.utc_now(), site) end
  stopped? = fn -> receive do :stop -> true after 0 -> false end end
  still? = fn ->
    s = Mount.snapshot(id)
    not s.axes.ra.running and not s.axes.dec.running and Controller.Sky.Tracker.status(id) == nil
  end
  # longest first: each step is four times shorter
  speeds = ~w(30 15 4 1 1/4 1/15 1/60 1/250 1/1000)
  # where to stop, in degrees of the Sun below the horizon. On 13 October the first run stopped at 3.5 with the sky
  # still far too dark for ISO 100 at f/10 (30 s read 54 of 255): this telescope needs the last three degrees.
  until = String.to_float(System.get_env("FLATS_UNTIL") || "-0.5")

  wait = fn wait ->
    cond do
      stopped?.() -> :asked
      not still?.() -> :moving
      sun.() >= -9.5 -> :go
      true -> Process.sleep(30_000); wait.(wait)
    end
  end

  take = fn ->
    before = (StillCamera.status().last || %{})[:seq] || 0
    StillCamera.shoot()
    Enum.find_value(1..150, fn _ ->
      Process.sleep(1000)
      s = StillCamera.status()
      if not s.busy and s.last && s.last[:seq] > before, do: s.last
    end)
  end

  case wait.(wait) do
    :go ->
      StillCamera.continuous(false)
      say.("starting, the Sun #{Float.round(sun.(), 1)} degrees")

      loop = fn loop, i, good, shots ->
        cond do
          good >= 24 -> {:done, good}
          shots >= 70 -> {:shots, good}
          sun.() > until -> {:sun, good}
          stopped?.() -> {:asked, good}
          not still?.() -> {:moving, good}
          true ->
            speed = Enum.at(speeds, i)
            if StillCamera.status().camera.settings[:shutter] != speed or StillCamera.status().camera.settings[:iso] != 100, do: StillCamera.set(iso: 100, shutter: speed)
            last = take.()
            bg = last && last[:background]
            cond do
              not is_number(bg) -> say.("no picture or nothing measured at #{speed} s"); loop.(loop, i, good, shots + 1)
              # the grey copy's sky, 0 to 255: mid-scale in the RAW is about 100 to 205 here
              bg > 205 and i < length(speeds) - 1 -> say.("#{speed} s reads #{bg}: shorter"); loop.(loop, i + 1, good, shots + 1)
              bg < 100 and i > 0 -> say.("#{speed} s reads #{bg}: longer"); loop.(loop, i - 1, good, shots + 1)
              bg < 100 -> say.("#{speed} s reads #{bg}: too dark yet, waiting"); Process.sleep(45_000); loop.(loop, i, good, shots + 1)
              true -> say.("#{good + 1}: #{speed} s reads #{bg}, the Sun #{Float.round(sun.(), 1)}"); loop.(loop, i, good + 1, shots + 1)
            end
        end
      end

      result = loop.(loop, 0, 0, 0)
      StillCamera.set(iso: 6400, shutter: "2")
      say.("finished: #{inspect(result)}")

    why ->
      say.("not started: #{inspect(why)}")
  end
end

pid = spawn(runner)
IO.puts("S flats runner #{inspect(pid)}")
