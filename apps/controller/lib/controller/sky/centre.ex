defmodule Controller.Sky.Centre do
  @moduledoc """
  Go To and Centre (#114): go to a target, take a picture with the camera on
  the telescope, plate solve it, and nudge by what the picture says, until the
  target is within `tolerance` of the middle. Then the model's hold keeps it.

      Centre.start("ttyUSB0", obj)               # obj: %{name, ra_deg, dec_deg}
      Centre.start("ttyUSB0", obj, flip: true)   # when the Go To needs the other side of the pier
      Centre.status("ttyUSB0")                   # %{phase, words, target, tries, off_arcmin, done, ok}

  **The nudge is local.** The alignment's global fit is a few arcminutes out
  somewhere on a mount set down anyhow, and refitting it with one more point
  only moves that error around (the night of 3 October). So the picture's
  answer is used where it was taken: the encoders the model gives for the
  solved place and for the target, both on the pose the mount is in, and the
  difference is the move. The model tracker, which pauses for any goto and
  then holds what it was last handed (`Controller.Sky.Tracker`), is handed
  the centred place with every nudge.

  It goes through the same Go To as every page (`Pointing.slew/5`), so a
  target that needs a meridian flip is refused until asked with `flip: true`,
  as a page asks. Pictures are the stills camera's finders
  (`Controller.StillCamera.finder/1`): solved ahead of the queue, with the
  plates so far as the solver's hint. STOP anywhere ends it on the spot. One
  run per mount; broadcasts `{:centre, mount_id, status}` on `"centre"`.
  """
  use GenServer

  alias Controller.StillCamera
  alias Controller.Sky.{Astro, Pointing, Tracker}

  @tolerance_arcmin 2.0
  @tries 3
  @settle_ms 2_500
  @deadline_ms 45_000
  # how long a Go To has to show it started before it is taken as landed (or never begun)
  @start_ms 3_000
  # a nudge bigger than this is not a nudge: the picture or the model is wrong, so stop and say so
  @max_nudge_deg 3.0

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Go to `obj` (`%{name, ra_deg, dec_deg}`) with mount `id` and centre it. Options:
  `tolerance_arcmin:` (2), `tries:` (3 pictures at most), `settle_ms:` (2500), `deadline_ms:`
  for each solve (45 000), `flip:` and `watched:` as `Pointing.slew/5` takes them, and `go: false`
  to centre where it is without a Go To first (the target already in the field).
  """
  def start(id, obj, opts \\ []), do: GenServer.call(__MODULE__, {:start, id, obj, opts})

  @doc "Stop, where it is (the hold carries on)."
  def stop(id), do: GenServer.call(__MODULE__, {:stop, id})

  @doc "The run for mount `id`: nil, or `%{phase, words, target, tries, off_arcmin, done, ok}`."
  def status(id), do: :persistent_term.get({__MODULE__, id}, nil)

  def subscribe, do: Telescope.subscribe("centre")

  # -- the process ---------------------------------------------------------------------------

  @impl true
  def init(_), do: {:ok, %{}}

  @impl true
  def handle_call({:start, id, obj, opts}, _from, runs) do
    cond do
      match?(%{done: false}, runs[id]) ->
        {:reply, {:error, :running}, runs}

      snap(id) == nil ->
        {:reply, {:error, :no_mount}, runs}

      not match?(%{camera: %{state: :ready}}, safe(fn -> StillCamera.status() end)) ->
        {:reply, {:error, :no_camera}, runs}

      true ->
        run = %{
          id: id,
          ref: Enum.find(Mount.list(), &(&1.id == id)),
          target: Map.take(obj, [:id, :name, :ra_deg, :dec_deg]),
          obj: obj,
          opts: opts,
          tolerance: Keyword.get(opts, :tolerance_arcmin, @tolerance_arcmin),
          max_tries: Keyword.get(opts, :tries, @tries),
          tries: 0,
          off_arcmin: nil,
          estop0: snap(id)[:estop_at],
          task: nil,
          phase: :starting,
          words: "Starting",
          done: false,
          ok: nil
        }

        case if(Keyword.get(opts, :go, true), do: go(run), else: {:ok, run}) do
          {:ok, run} ->
            send(self(), {:watch, id})
            {:reply, :ok, put(runs, shoot(run, Keyword.get(opts, :go, true)))}

          {:error, why} ->
            {:reply, {:error, why}, put(runs, finish(run, false, refusal(why, run.target.name)))}
        end
    end
  end

  def handle_call({:stop, id}, _from, runs) do
    case runs[id] do
      %{done: false} = run -> {:reply, :ok, put(runs, finish(run, false, "Stopped"))}
      _ -> {:reply, :ok, runs}
    end
  end

  @impl true
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

  # a picture solved, or not
  def handle_info({:solved, id, result}, runs) do
    case runs[id] do
      %{done: false} = run -> {:noreply, put(runs, judge(%{run | task: nil}, result))}
      _ -> {:noreply, runs}
    end
  end

  def handle_info(_, runs), do: {:noreply, runs}

  # -- the steps ------------------------------------------------------------------------------

  defp go(run) do
    ctx = Pointing.context(DateTime.utc_now(), run.id)
    slew = Keyword.take(run.opts, [:flip, :watched]) ++ [track: true]

    case Pointing.slew(run.ref, snap(run.id), run.obj, ctx, slew) do
      {:ok, _, _} -> {:ok, say(run, :going, "Going to #{run.target.name}")}
      {:error, why} -> {:error, why}
    end
  end

  # once the mount has landed and settled: a finder picture, solved
  defp shoot(run, after_move?) do
    parent = self()
    id = run.id
    settle = Keyword.get(run.opts, :settle_ms, @settle_ms)
    deadline = Keyword.get(run.opts, :deadline_ms, @deadline_ms)

    {:ok, pid} =
      Task.start(fn ->
        if after_move?, do: landed(id)
        Process.sleep(settle)
        result = StillCamera.finder(mount: id, scale: StillCamera.field_scale(), min_stars: 6, deadline: deadline)
        send(parent, {:solved, id, result})
      end)

    %{run | task: pid, tries: run.tries + 1}
    |> say(:solving, "Taking and plate solving picture #{run.tries + 1} of #{run.target.name}")
  end

  defp judge(run, {:ok, %{from: :solve, ra_deg: ra, dec_deg: dec}}) do
    t = run.target
    off = Astro.separation_radec(ra, dec, t.ra_deg, t.dec_deg) * 60
    run = %{run | off_arcmin: off}

    cond do
      off <= run.tolerance ->
        finish(run, true, "#{t.name} centred: #{fmt(off)}′ from the middle")

      run.tries >= run.max_tries ->
        finish(run, false, "#{t.name} is #{fmt(off)}′ from the middle after #{run.tries} pictures. Center it by hand")

      true ->
        case nudge(run, {ra, dec}) do
          :ok -> shoot(say(run, :nudging, "#{fmt(off)}′ off: nudging"), true)
          {:error, why} -> finish(run, false, "#{fmt(off)}′ off and couldn't nudge: #{why}")
        end
    end
  end

  defp judge(run, {:error, why}) do
    if run.tries >= run.max_tries,
      do: finish(run, false, "The pictures didn't plate solve (#{Controller.AutoAlign.still_words(why)})"),
      else: shoot(say(run, :retrying, "Picture #{run.tries}: #{Controller.AutoAlign.still_words(why)}; trying again"), false)
  end

  defp judge(run, other), do: finish(run, false, "No answer from the camera: #{inspect(other)}")

  # The picture says the tube is at the solved place; the model believes it is somewhere a little
  # off that. That difference is the model's error here, and it is the same for a target a few
  # arcminutes away: so the model is asked for the target moved by it (the aim), the mount goes
  # there, and the hold is handed the aim, named for the target. The hold treats any goto as its
  # own and would otherwise pull back to the model's idea of the target once it landed.
  defp nudge(run, {ra, dec}) do
    ctx = Pointing.context(DateTime.utc_now(), run.id)
    snap = snap(run.id)
    cur = {snap.axes.ra.degrees, snap.axes.dec.degrees}
    t = run.target

    with {b_ra, b_dec} <- Pointing.scope_radec(snap, ctx),
         aim = %{name: t.name, ra_deg: norm360(t.ra_deg + Astro.norm180(b_ra - ra)), dec_deg: t.dec_deg + (b_dec - dec)},
         {ra_a, dec_a} <- Pointing.axes_for(aim, ctx, near: cur) do
      d_ra = Astro.norm180(ra_a - elem(cur, 0))
      d_dec = Astro.norm180(dec_a - elem(cur, 1))

      cond do
        abs(d_ra) > @max_nudge_deg or abs(d_dec) > @max_nudge_deg ->
          {:error, "the move would be #{fmt(d_ra)}° and #{fmt(d_dec)}°, too big for a nudge"}

        true ->
          Tracker.track(run.id, aim, run.obj)
          safe(fn -> if abs(d_ra) > 1.0e-4, do: Mount.goto_relative(run.ref, :ra, d_ra) end)
          safe(fn -> if abs(d_dec) > 1.0e-4, do: Mount.goto_relative(run.ref, :dec, d_dec) end)
          :ok
      end
    else
      _ -> {:error, "no alignment to work the move out with"}
    end
  end

  defp norm360(x), do: x - 360 * Float.floor(x / 360)

  # Until both axes' gotos have finished: seen started and then stopped, or never seen at all.
  defp landed(id, started? \\ false, since \\ System.monotonic_time(:millisecond)) do
    pending = moving?(id)

    cond do
      pending -> Process.sleep(250) && landed(id, true, since)
      started? -> :ok
      System.monotonic_time(:millisecond) - since > @start_ms -> :ok
      true -> Process.sleep(250) && landed(id, false, since)
    end
  end

  defp finish(run, ok, words) do
    Telescope.Events.emit(:centre, :done, %{id: run.id, ok: ok, target: run.target[:name], tries: run.tries, off_arcmin: run.off_arcmin})
    %{run | done: true, ok: ok} |> say(:done, words)
  end

  defp say(run, phase, words), do: %{run | phase: phase, words: words}

  defp refusal({:flip, %{past: past}}, name), do: "#{name} needs the tube on the other side of the mount (the counterweight would be #{fmt(past)}° above level). Ask again with the flip"
  defp refusal(why, name), do: Pointing.refusal_words(why, name)

  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp fmt(_), do: "?"

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

  defp snap(id) do
    Mount.snapshot(id)
  catch
    :exit, _ -> nil
  end

  defp put(runs, run) do
    public = Map.take(run, [:phase, :words, :target, :tries, :off_arcmin, :done, :ok])
    :persistent_term.put({__MODULE__, run.id}, public)
    Telescope.broadcast("centre", {:centre, run.id, public})
    Map.put(runs, run.id, run)
  end

  defp safe(fun) do
    fun.()
  catch
    :exit, _ -> nil
  end
end
