defmodule Controller.AutoAlign do
  @moduledoc """
  Auto Align: put the camera in the focuser, tap once, and the telescope
  works out where it's pointing by itself.

  It takes a frame with the telescope camera, has it plate solved on the
  box (`Controller.Plates`, the same queue Align by Photo uses), moves the
  mount a little, and does it again, spreading the pictures over a patch of
  sky about 30° across. Once enough of them agree (`:enough`, 4), they become
  the mount's alignment, the same as "Use This Alignment" after photos from
  a phone. It needs no home: on a mount whose home was never set its last
  words ask which side the counterweight is on, the one thing no picture can
  say, and Go To waits for the answer (`Controller.Sky.Pointing.side_guessed?/2`).

  **Moves stay small and are only ever this one's own.** Each is at most
  15° on RA and 10° on Dec from where it started, so it never swings past the
  mount's limits from a sensible starting pose; the mount's own sidereal
  drive keeps the stars still between moves. STOP anywhere ends it on the
  spot, and so does `stop/1`.

  **It knows a bad picture when it sees one.** Every picture is judged
  before a solver sees it (`Controller.ScopeCamera.Image.verdict/3`): too
  bright (the Moon, a light, a lit garage), no stars (clouds, a wall, the
  lens cap), blurry blobs, or too few stars. A bad picture isn't solved; the
  mount moves on to the next spot by itself. A picture with too few stars
  is tried once more with more frames stacked. Three bad pictures in a row
  and it **hands the mount to you**: move it to open sky with the pad or
  the touchpad and tap Continue (`continue/1`), and it carries on from
  wherever you left it, keeping the pictures it already placed.

  **It takes whichever camera is on the telescope** (#111). The stills
  camera (the Sony a6000) when it is ready, else the telescope camera. With
  the stills camera each picture is a finder (`Controller.StillCamera.finder/1`):
  set to a finder exposure first (ISO 6400, 2 s, which plate solved on the
  night of 3 October), solved ahead of the queue with a deadline of its own,
  and added to the mount's plates like any other. Nothing to stack: a picture
  that doesn't solve is a miss and the mount moves on. Continuous shooting
  stands down for the run and comes back after it.

  One run per mount. Broadcasts `{:auto_align, mount_id, status}` on
  `"auto_align"` at every step.
  """
  use GenServer

  alias Controller.{Plates, ScopeCamera, StillCamera}

  # where each picture is taken, relative to the start: degrees on RA and Dec
  @plan [{0, 0}, {15, 0}, {15, 10}, {0, 10}, {-15, 10}, {-15, 0}, {-15, -10}, {0, -10}]
  @enough 4
  @give_up_after 3
  # a telescope camera sees a small patch of sky: about 0.1° to 0.7° across
  # for a 1/2.8" sensor on 500 to 2500 mm of focal length
  @scale {0.08, 0.8}
  @blind_ms 240_000
  @hinted_ms 90_000
  # pictures for the plate solver, not for focusing: as long as the camera
  # allows (up to 2 s) and high gain, because faint stars are what it matches
  # on (the SV105C tops out at 1 s; at gain 0 its frames come back flat)
  @exposure_ms 2_000
  @gain 80
  # the stills camera: a finder exposure, how long after a move (its own settle mark is 2 s), and
  # how long a solve may take: the first is blind, the rest have the plates so far as a hint
  @still_iso 6400
  @still_shutter "2"
  @still_settle_ms 2_500
  @still_blind_ms 120_000
  @still_hinted_ms 45_000
  # a picture already on its way (continuous shooting stopping): ask again this often, this many times
  @busy_ms 2_000
  @busy_tries 60

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Start finding where mount `id` points. Options: `plan:`, `enough:`,
  `settle_ms:`, `stack:`, and `camera:` (`:still` or `:scope`; whichever is
  ready when not given, `camera/0`). For the telescope camera, the pictures'
  `exposure_ms:` (2000, or as long as the camera goes) and `gain:` (80), which
  leave the focus settings alone; for the stills camera, `iso:` (6400) and
  `shutter:` ("2"), which it is set to before the first picture (`nil` leaves
  it as it is).
  """
  def start(id, opts \\ []), do: GenServer.call(__MODULE__, {:start, id, opts})

  @doc """
  The camera a run would take: `:still` when the stills camera is ready, `:scope` when the
  telescope camera is there, else nil.
  """
  def camera do
    cond do
      match?(%{camera: %{state: :ready}}, safe(fn -> StillCamera.status() end)) -> :still
      not match?(%{camera: nil}, safe(fn -> ScopeCamera.status() end) || %{camera: nil}) -> :scope
      true -> nil
    end
  end

  @doc "Stop, where it is."
  def stop(id), do: GenServer.call(__MODULE__, {:stop, id})

  @doc "Carry on after it handed the mount over (you moved it to better sky)."
  def continue(id), do: GenServer.call(__MODULE__, {:continue, id})

  @doc "The run for mount `id`: nil, or `%{phase, words, picture, solved, of, done, ok}`."
  def status(id), do: :persistent_term.get({__MODULE__, id}, nil)

  def subscribe, do: Telescope.subscribe("auto_align")

  # -- the process ---------------------------------------------------------------------------

  @impl true
  def init(_), do: {:ok, %{}}

  @impl true
  def handle_call({:start, id, opts}, _from, runs) do
    camera = Keyword.get_lazy(opts, :camera, &camera/0)

    cond do
      match?(%{done: false}, runs[id]) ->
        {:reply, {:error, :running}, runs}

      snap(id) == nil ->
        {:reply, {:error, :no_mount}, runs}

      camera == nil ->
        {:reply, {:error, :no_camera}, runs}

      true ->
        Plates.clear(id)
        ref = Enum.find(Mount.list(), &(&1.id == id))
        # the model's hold would pull each move back toward its old target
        Controller.Sky.Tracker.stop(id, halt: false)
        # video has the camera: pictures need it back
        if camera == :scope, do: ScopeCamera.video(false)
        # one picture at a time, and they are this run's: continuous shooting stands down until it ends
        was_shooting = camera == :still and StillCamera.status().shooting == true
        if was_shooting, do: safe(fn -> StillCamera.continuous(false) end)
        # the stars have to stand still between moves
        if snap(id).tracking == :off, do: safe(fn -> Mount.track(ref, :sidereal) end)

        run = %{
          id: id,
          ref: ref,
          camera: camera,
          was_shooting: was_shooting,
          iso: Keyword.get(opts, :iso, @still_iso),
          shutter: Keyword.get(opts, :shutter, @still_shutter),
          busy: 0,
          exposed: false,
          plan: Keyword.get(opts, :plan, @plan),
          enough: Keyword.get(opts, :enough, @enough),
          settle_ms: Keyword.get(opts, :settle_ms, if(camera == :still, do: @still_settle_ms, else: 1_500)),
          stack: Keyword.get(opts, :stack, nil),
          exposure_ms: Keyword.get(opts, :exposure_ms, @exposure_ms),
          gain: Keyword.get(opts, :gain, @gain),
          at: {0, 0},
          step: 0,
          picture: 0,
          solved: 0,
          misses: 0,
          retried: false,
          plate: nil,
          started_ms: System.monotonic_time(:millisecond),
          # the last STOP before this run: any other one ends it
          estop0: snap(id)[:estop_at],
          phase: :starting,
          words: "Starting",
          done: false,
          ok: nil
        }

        Plates.subscribe(id)
        send(self(), {:watch, id})

        case if(Keyword.get(opts, :overhead, false), do: overhead(run), else: {:ok, run}) do
          {:ok, run} ->
            send(self(), {:next, id})
            {:reply, :ok, put(runs, run)}

          {:error, why} ->
            {:reply, {:error, why}, put(runs, finish(run, false, "Couldn't point it up high: #{Controller.Words.error(why)}"))}
        end
    end
  end

  # from where the person left it: a fresh plan around here, the placed pictures kept
  def handle_call({:continue, id}, _from, runs) do
    case runs[id] do
      %{done: false, phase: :waiting} = run ->
        send(self(), {:next, id})
        {:reply, :ok, put(runs, %{run | misses: 0, retried: false, at: {0, 0}, step: 0} |> say(:starting, "Carrying on from here"))}

      _ ->
        {:reply, {:error, :not_waiting}, runs}
    end
  end

  def handle_call({:stop, id}, _from, runs) do
    case runs[id] do
      %{done: false} = run -> {:reply, :ok, put(runs, finish(run, false, "Stopped"))}
      _ -> {:reply, :ok, runs}
    end
  end

  @impl true
  # STOP anywhere, whatever it's doing
  def handle_info({:watch, id}, runs) do
    case runs[id] do
      %{done: false} = run ->
        if stopped?(run) do
          {:noreply, put(runs, finish(run, false, "Stopped: STOP was pressed"))}
        else
          Process.send_after(self(), {:watch, id}, 500)
          {:noreply, runs}
        end

      _ ->
        {:noreply, runs}
    end
  end

  # the next picture, once the mount has stopped moving
  def handle_info({:next, id}, runs) do
    with %{done: false} = run when run.phase != :waiting <- runs[id] do
      cond do
        stopped?(run) -> {:noreply, put(runs, finish(run, false, "Stopped: STOP was pressed"))}
        moving?(id) -> Process.send_after(self(), {:next, id}, 500) && {:noreply, runs}
        true -> {:noreply, put(runs, shoot(run))}
      end
    else
      _ -> {:noreply, runs}
    end
  end

  # the picture's plate, solved or not
  def handle_info({:plates, id, view}, runs) do
    with %{done: false, plate: n} = run when is_integer(n) <- runs[id],
         %{state: state} = plate when state in [:solved, :failed] <- Enum.find(view.plates, &(&1.n == n)) do
      {:noreply, put(runs, solved(run, plate))}
    else
      _ -> {:noreply, runs}
    end
  end

  # a picture taken (by a task, so a slow camera never blocks a STOP)
  def handle_info({:shot, id, result}, runs) do
    with %{done: false} = run <- runs[id] do
      case result do
        # the stills camera's finder: solved or not by the time it answers
        {:still, :solved} ->
          {:noreply, put(runs, solved(%{run | busy: 0}, %{state: :solved}))}

        {:still, :moving} ->
          {:noreply, put(runs, solved(%{run | busy: 0}, %{reason: "moving"}))}

        # a picture of its own still on its way (continuous shooting was stopping): ask again
        {:still, :busy} when run.busy < @busy_tries ->
          Process.send_after(self(), {:next, id}, @busy_ms)
          {:noreply, put(runs, %{run | busy: run.busy + 1, picture: run.picture - 1} |> say(:shooting, "Waiting for the camera to finish a picture"))}

        {:still, why} ->
          {:noreply, put(runs, missed(%{run | busy: 0}, "Frame #{run.picture}: #{still_words(why)}"))}

        {:ok, n} ->
          run = %{run | plate: n} |> say(:solving, "Plate solving frame #{run.picture}")

          # it may have been solved already, before we knew its number
          case Enum.find((safe(fn -> Plates.view(id) end) || %{plates: []}).plates, &(&1.n == n)) do
            %{state: state} = plate when state in [:solved, :failed] -> {:noreply, put(runs, solved(run, plate))}
            _ -> {:noreply, put(runs, run)}
          end

        # not worth solving: the garage, a cloud, the Moon
        {:bad, :few_stars} when not run.retried ->
          send(self(), {:next, id})
          {:noreply, put(runs, %{run | retried: true} |> say(:retrying, "Only a few stars in frame #{run.picture}; trying again with more exposures stacked"))}

        {:bad, verdict} ->
          {:noreply, put(runs, missed(run, "Frame #{run.picture}: #{Controller.ScopeCamera.Image.verdict_words(verdict)}"))}

        {:error, reason} ->
          {:noreply, put(runs, missed(run, "The camera didn't give a frame: #{Controller.Words.error(reason)}"))}
      end
    else
      _ -> {:noreply, runs}
    end
  end

  def handle_info(_, runs), do: {:noreply, runs}

  # -- one picture ----------------------------------------------------------------------------

  # The stills camera: a finder picture, which is solved (or not) by the time it answers. The first
  # one sets the finder exposure; a camera that won't turn its dials is used as it is set.
  defp shoot(%{camera: :still} = run) do
    parent = self()
    id = run.id
    picture = run.picture + 1
    settle = run.settle_ms
    first? = not run.exposed
    exposure = Enum.reject([iso: run.iso, shutter: run.shutter], fn {_, v} -> is_nil(v) end)
    deadline = if run.solved > 0, do: @still_hinted_ms, else: @still_blind_ms

    Task.Supervisor.start_child(Controller.ScopeCamera.Tasks, fn ->
      Process.sleep(settle)
      if first? and exposure != [] and not set?(exposure), do: safe(fn -> StillCamera.set(exposure) end)

      result =
        case StillCamera.finder(mount: id, scale: StillCamera.field_scale(), min_stars: 6, deadline: deadline) do
          {:ok, %{from: :solve}} -> :solved
          {:error, why} -> why
          other -> other
        end

      send(parent, {:shot, id, {:still, result}})
    end)

    %{run | picture: picture, plate: nil, exposed: true}
    |> say(:shooting, if(first?, do: "Setting the camera for stars, then taking frame #{picture}", else: "Taking and plate solving frame #{picture}"))
  end

  defp shoot(run) do
    parent = self()
    id = run.id
    picture = run.picture + 1
    stack = run.stack || (if run.retried, do: 8, else: nil)
    settle = run.settle_ms
    hinted? = run.solved > 0
    exposure = run.exposure_ms
    gain = run.gain

    Task.Supervisor.start_child(Controller.ScopeCamera.Tasks, fn ->
      Process.sleep(settle)
      snap = snap(id)
      cap = Plates.capture(snap, report: report(id))
      opts = [mount: id, exposure_ms: exposure, gain: gain] ++ if(stack, do: [stack: stack], else: [])

      result =
        with {:ok, %{pgm: pgm, verdict: verdict, focus: focus}} <- ScopeCamera.grab(opts),
             true <- verdict in [:stars, :blurry] || verdict do
          Plates.add(id, pgm, cap,
            scale: @scale,
            min_stars: 6,
            timeout: if(hinted?, do: @hinted_ms, else: @blind_ms),
            downsample: downsample(focus.hfr)
          )
        else
          bad when is_atom(bad) -> {:bad, bad}
          other -> other
        end

      send(parent, {:shot, id, result})
    end)

    %{run | picture: picture, plate: nil}
    |> say(:shooting, "Taking frame #{picture}#{if stack, do: " (#{stack} exposures stacked)", else: ""}")
  end

  defp solved(run, %{state: :solved}) do
    run = %{run | solved: run.solved + 1, misses: 0, retried: false, plate: nil}

    if run.solved >= run.enough do
      case Plates.use_alignment(run.id) do
        {:ok, st} ->
          finish(run, true, found_words(st))

        {:error, e} ->
          finish(run, false, "The frames were plate solved but couldn't be used: #{Controller.Words.error(e)}")
      end
    else
      move(run)
    end
  end

  # taken while the mount was still settling: the same spot again, no harm done
  defp solved(run, %{reason: "moving"}) do
    Process.send_after(self(), {:next, run.id}, 1_000)
    %{run | plate: nil} |> say(:retrying, "The mount was still settling; taking frame #{run.picture} again")
  end

  defp solved(run, %{reason: reason}) do
    # no stars: one more try here with more light, then move on
    if reason in ["too_few_stars", "no_solution"] and not run.retried do
      send(self(), {:next, run.id})
      %{run | retried: true, plate: nil} |> say(:retrying, "No match in frame #{run.picture}; trying again with more exposures stacked")
    else
      missed(run, "Frame #{run.picture} didn't plate solve (#{reason |> to_string() |> String.replace("_", " ")})")
    end
  end

  # On a mount whose home was never set, no picture can say which side of the pier the
  # counterweight is on, and Go To waits for it (#113): the last words are the question.
  defp found_words(st) do
    agree = "#{st.n} frames agree#{if st.rms_arcmin, do: " to #{round(st.rms_arcmin * 10) / 10}′", else: ""}"

    if st[:counterweight] == :guessed,
      do: "Aligned: #{agree}. Is the counterweight bar below or above level right now?",
      else: "Found it: #{agree}. Go To uses this now"
  end

  defp missed(run, why) do
    run = %{run | misses: run.misses + 1, retried: false, plate: nil}

    if run.misses >= @give_up_after do
      # hand the mount over: a person can see what the camera can't
      run |> say(:waiting, "#{why}. Three bad frames in a row. Move the telescope to open sky with the game controller or the touchpad, then tap Continue")
    else
      move(run |> say(:missed, why))
    end
  end

  # to the next spot in the plan, relative to where it is now
  # Out-of-focus stars are rings, and the solver's star finder breaks a ring
  # into several "stars". Shrinking the picture first turns a ring back into
  # one dot: measured on catalog fields, rings 12 px across solve at 4x and
  # fail at 2x. So the softer the stars, the more it's shrunk.
  @doc false
  def downsample(hfr) when is_number(hfr) and hfr >= 5, do: 4
  def downsample(hfr) when is_number(hfr) and hfr >= 2.5, do: 2
  def downsample(_), do: 1

  defp move(%{step: step, plan: plan} = run) do
    case Enum.at(plan, step + 1) do
      nil ->
        finish(run, run.solved >= 2, "Out of places to look: #{run.solved} frames plate solved")

      {ra, dec} = next ->
        {ra0, dec0} = run.at
        safe(fn -> if ra - ra0 != 0, do: Mount.goto_relative(run.ref, :ra, (ra - ra0) / 1) end)
        safe(fn -> if dec - dec0 != 0, do: Mount.goto_relative(run.ref, :dec, (dec - dec0) / 1) end)
        Process.send_after(self(), {:next, run.id}, 700)
        %{run | at: next, step: step + 1} |> say(:moving, "Moving a little to the next patch of sky")
    end
  end

  # From home the tube looks along the polar axis, where turning RA turns the view about its own
  # middle and the pictures can't tell the axes apart. So first, up high: the sky straight overhead
  # (the most open, over trees and roofs), through the zeroed mount's first-order pointing. On a
  # tripod set down anyhow that lands within the polar axis's error of overhead, which is open sky
  # all the same. On the meridian the counterweight stays straight down: only Dec turns.
  defp overhead(run) do
    ctx = Controller.Sky.Pointing.context(DateTime.utc_now(), run.id)
    up = %{ra_deg: Controller.Sky.Astro.lst_deg(ctx.now, ctx.site.lon), dec_deg: ctx.site.lat / 1}

    case Controller.Sky.Pointing.slew(run.ref, snap(run.id), up, ctx, track: false) do
      {:ok, _, _} ->
        # the driver's sidereal drive, back on: the goto may have turned it off for a model
        if snap(run.id)[:tracking] == :off, do: safe(fn -> Mount.track(run.ref, :sidereal) end)
        {:ok, say(run, :moving, "Pointing up high, where the sky is most open")}

      {:error, why} ->
        {:error, why}
    end
  end

  defp finish(run, ok, words) do
    Telescope.Events.emit(:auto_align, :done, %{id: run.id, ok: ok, solved: run.solved, pictures: run.picture, camera: run.camera})
    if run.was_shooting, do: safe(fn -> StillCamera.continuous(true) end)
    %{run | done: true, ok: ok} |> say(:done, words)
  end

  defp say(run, phase, words), do: %{run | phase: phase, words: words}

  # the stills camera already reads the finder exposure: turning its dials takes seconds each
  defp set?(exposure) do
    case safe(fn -> StillCamera.status() end) do
      %{camera: %{settings: %{} = now}} -> Enum.all?(exposure, fn {k, want} -> same?(k, now, want) end)
      _ -> false
    end
  end

  defp same?(:iso, now, want), do: now[:iso] == want
  defp same?(:shutter, %{shutter_s: s}, want) when is_number(s), do: abs(s - seconds(want)) < 0.01
  defp same?(_, _, _), do: false

  defp seconds(n) when is_number(n), do: n / 1
  defp seconds(s) when is_binary(s) do
    case String.split(s, "/") do
      [a, b] -> String.to_integer(a) / String.to_integer(b)
      [a] -> elem(Float.parse(a), 0)
    end
  rescue
    _ -> -1.0
  end

  @doc false
  # why a finder picture didn't place, in words
  def still_words(:too_few_stars), do: "too few stars to plate solve (a tree, cloud, or the focus)"
  def still_words(:no_solution), do: "the stars didn't match the sky (blurred, or the focal length is far off)"
  def still_words(:deadline), do: "the plate solve ran out of time"
  def still_words(:no_camera), do: "the camera isn't answering"
  def still_words(:not_taken), do: "not taken: the SD card is nearly full"
  def still_words(:busy), do: "the camera stayed busy"
  def still_words(:below_horizon), do: "it solved below the horizon (check the site)"
  def still_words(why), do: "not plate solved (#{Controller.Words.error(why)})"

  # -- reading the world -------------------------------------------------------------------------

  defp stopped?(run) do
    case snap(run.id) do
      %{estop_at: t} when is_integer(t) -> t != run.estop0
      _ -> false
    end
  end

  defp moving?(id) do
    case snap(id) do
      %{axes: axes} -> Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end)
      _ -> false
    end
  end

  defp report(id) do
    Plates.view(id)[:report]
  catch
    :exit, _ -> nil
  end

  defp snap(id) do
    Mount.snapshot(id)
  catch
    :exit, _ -> nil
  end

  defp put(runs, run) do
    public = Map.take(run, [:phase, :words, :picture, :solved, :enough, :done, :ok, :camera])
    :persistent_term.put({__MODULE__, run.id}, public)
    Telescope.broadcast("auto_align", {:auto_align, run.id, public})
    Map.put(runs, run.id, run)
  end

  defp safe(fun) do
    fun.()
  catch
    :exit, _ -> nil
  end
end
