defmodule Controller.Plates do
  @moduledoc """
  Photos through the eyepiece, queued and plate-solved in the background, so
  a person can move, snap, move, snap without waiting for any of them.

      cap = Plates.capture(snap)                  # the moment the photo is chosen
      {:ok, 4} = Plates.add("eq6r", jpeg, cap)    # later, when its bytes arrive
      Plates.view("eq6r")                         # plates, queue positions, the fit
      Plates.subscribe("eq6r")                    # {:plates, "eq6r", view} on every change

  **A plate** is one photo and everything needed to use it: the capture
  (both axes' encoder degrees and steps, whether either was running, whether
  the mount was tracking, when), the photo's own time from EXIF, the file on
  disk, and the solve. It goes `:queued -> :solving -> :solved | :failed`
  (with a reason). A plate captured while the scope was slewing is kept but
  failed as "moving": its encoders and its sky do not belong together.

  **The queue** solves up to `workers` plates at once (a knob:
  `start_link(workers: n)`, `config :controller, :plate_workers`; by default
  one fewer than this machine's cores, one on a Nerves box), oldest first,
  each in its own task under `Controller.Plates.Tasks`. A solve that crashes,
  hangs past its deadline, or is removed fails (or forgets) that plate
  alone. Every change is saved (`Controller.Plates.Store`) and broadcast on
  `"plates:<mount id>"`, so every phone sees the queue move. A restart loses
  nothing: plates that were solving are queued again.

  **The fit** is the mount's model from every solved plate
  (`Controller.Sky.Polar`), and the queue never computes it: a cold fit
  takes seconds on a Pi, and a queue that fitted after every plate was deaf
  for longer with each one (#112). It runs in a task under the same
  supervisor, one at a time. Until it lands the view carries the last model
  and `fitting: true`; when it lands the view is broadcast again. Plates
  that solve meanwhile get one more fit afterwards, of all of them. A fit
  that crashes, or runs past its deadline (`start_link(fit_timeout: ms)`,
  `config :controller, :plate_fit_timeout`; 30 s), is dropped: the last
  model stays, and the view's `fit_notice` says so in one line until a fit
  lands. It is not tried again by itself; the next thing done with the
  photos (another one, a retry, Use This Alignment) asks again.
  `start_link(fit: SomeModule)` (or `config :controller, :plate_fit,
  SomeModule`) puts a module with `fit(samples, opts)` in `Polar`'s place,
  the way `Controller.Sky.Solve` takes its `backend:`.

  **A finder** (`add(..., finder: true)`) is a quick solve someone is
  waiting on, to check the aim before a series. It goes ahead of everything
  queued, and when every worker is busy one solve makes way for it and is
  queued again. It has a deadline of its own, counted from when it was
  added (`deadline:`, 30 s): not solved by then, it fails as "deadline",
  its solve is stopped, and the queue takes the next plate.

  **The moment** a plate belongs to: when the mount is tracking, the tube
  stays on the same sky, so the capture's time; when it stands still, the
  shutter's (EXIF DateTimeOriginal with its offset), or the capture's when
  the photo does not say. A photo more than 300 s older than its capture
  is refused (it was not taken at those encoders).

  The subtree gives up after repeated crashes rather than take the app down
  (`Controller.Plates.Supervisor`); `status/0` then says `:down` and
  `restart/0` brings it back.
  """
  use GenServer
  require Logger

  alias Controller.Plates.Store
  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Model, Photo, Pointing, Polar, Solve, Tracker}

  @solve_timeout 90_000
  # past the solver's own deadline, the queue stops waiting
  @grace_ms 15_000
  @max_age_s 300
  # faster than 12x sidereal is a slew, not tracking
  @moving_deg_s 0.05
  @tasks Controller.Plates.Tasks

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Workers when nothing says otherwise: one fewer than the cores here, one on a Nerves box."
  def default_workers do
    if Code.ensure_loaded?(Nerves.Runtime), do: 1, else: max(1, System.schedulers_online() - 1)
  end

  @doc "Follow one mount's plates: `{:plates, mount_id, view}` on every change."
  def subscribe(mount_id), do: Telescope.subscribe("plates:" <> mount_id)

  # -- capture: in the caller, at the moment the photo is chosen ----------------------------

  @doc """
  The mount as it is right now, for a photo just chosen: encoders (degrees
  and steps) of both axes, whether either is running, tracking, moving
  (slewing: a plate that cannot be used), the zero it counts from, the time,
  and where to tell the solver to look. `report:` (the fit so far) makes
  that hint tight. Pure but for reading the pointing model; runs in the
  caller, so the queue never waits on a mount.
  """
  def capture(snap, opts \\ [])
  def capture(nil, _opts), do: nil

  def capture(%{id: id, axes: %{ra: ra, dec: dec}} = snap, opts) do
    now = Keyword.get(opts, :now, DateTime.utc_now())
    tracker? = Tracker.active?(id)
    tracking? = snap[:tracking] not in [nil, :off] or tracker?

    %{
      mount: id,
      at: now,
      homed: snap[:homed] == true,
      homed_at: snap[:homed_at],
      tracking: tracking?,
      moving: moving?(snap, tracking?, tracker?),
      enc: %{
        ra_deg: ra.degrees / 1,
        dec_deg: dec.degrees / 1,
        ra_steps: ra[:steps],
        dec_steps: dec[:steps],
        ra_running: ra[:running] == true,
        dec_running: dec[:running] == true
      },
      hint: hint(snap, opts[:report], now)
    }
  end

  # Slewing, not tracking: a goto in flight, an axis faster than a tracker
  # ever goes, RA running with no tracking, Dec running with no model tracker.
  defp moving?(%{axes: axes}, tracking?, tracker?) do
    Enum.any?(axes, fn {_, ax} -> ax[:goto_pending] == true or abs(ax[:deg_per_s] || 0.0) > @moving_deg_s end) or
      (axes.ra[:running] == true and not tracking?) or
      (axes.dec[:running] == true and not tracker?)
  end

  @doc """
  Where the solver should look for a photo at these encoders: through the
  fit so far when there is one (tight), else through whatever pointing
  model is in force (loose), else nil.
  """
  def hint(snap, report, now) do
    site = Pointing.site()

    case report do
      %{n: n, params: p, signs: sg} when n >= 1 ->
        {ra, dec} = Model.radec(p, sg, snap.axes.ra.degrees, snap.axes.dec.degrees, site.lat, Astro.lst_deg(now, site.lon))
        %{ra_deg: ra, dec_deg: dec, radius_deg: hint_radius(n)}

      _ ->
        case Pointing.scope_radec(snap, Pointing.context(now, snap.id)) do
          {ra, dec} -> %{ra_deg: ra, dec_deg: dec, radius_deg: 20.0}
          _ -> nil
        end
    end
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end

  # How far to trust the fit so far. One plate fixes the offsets and leaves the
  # axis at the pole: on a mount set down 27 degrees off, a 13 degree move put
  # the next plate 6 degrees from the hint. Two plates can be met exactly by
  # the wrong geometry (the Dec axis running the other way), and then the hint
  # for the third is tens of degrees out. Three or more are a fit.
  defp hint_radius(1), do: 15.0
  defp hint_radius(2), do: 25.0
  defp hint_radius(_), do: 5.0

  # -- the API --------------------------------------------------------------------------------

  @doc """
  A photo's bytes, for a capture taken when it was chosen. `{:ok, n}`: plate
  n is queued (or kept as "moving"). Errors: `:no_mount`, `:not_homed`,
  `:unsupported_image`, `:old_photo`, `:down`. Options: `max_age_s:`, and
  for the solver, `scale:` `{low_deg, high_deg}` across the image (a camera
  at the telescope sees a much smaller patch of sky than a phone at the
  eyepiece), `min_stars:`, `nsigma:` (how far above the noise a star must
  stand: a camera's own JPEG wants about 10, or its grain is counted as
  thousands of stars), and `timeout:` in ms (a first, blind solve on a Pi can
  take minutes). `finder: true` is a solve someone is waiting on: ahead of
  the queue, and failed as "deadline" when it isn't solved within
  `deadline:` ms of being added (`finder_deadline/0`).
  """
  def add(mount_id, image, capture, opts \\ []) when is_binary(image), do: call({:add, mount_id, image, capture, opts}, 15_000)

  @doc "How long a finder has when nothing says otherwise (`config :controller, :finder_deadline_ms`, 30 s)."
  def finder_deadline, do: Application.get_env(:controller, :finder_deadline_ms, 30_000)

  @doc """
  The session as every page shows it: plates (with `ahead` for queued ones),
  the fit (`report`), applied or not. `fitting` is true while the model is
  being fitted again (`report` is the last one meanwhile); `fit_notice` is
  one line when the last fit was dropped, nil otherwise.
  """
  def view(mount_id), do: call({:view, mount_id})

  @doc "Queue a failed plate again (not one that was moving)."
  def retry(mount_id, n), do: call({:retry, mount_id, n})

  @doc "Forget a plate, and stop its solve if it is running."
  def remove(mount_id, n), do: call({:remove, mount_id, n})

  @doc "Start over: a new, empty session (the old one's files stay on disk)."
  def clear(mount_id), do: call({:clear, mount_id})

  @doc """
  "Use This Alignment": the solved plates become the mount's Star Align
  samples (replacing any stars), fitted and used for GoTo the same way.
  `{:ok, Lineup.status}` or `{:error, :too_few}`.
  """
  def use_alignment(mount_id) do
    # the fit reads the mount (is it still zeroed?): done here, never in the queue
    with {:ok, samples, home_at} <- call({:samples, mount_id}) do
      status = Lineup.replace(mount_id, samples, home_at)
      call({:applied, mount_id})
      Telescope.Events.emit(:plates, :used, %{id: mount_id, n: length(samples)})
      {:ok, status}
    end
  end

  @doc """
  `%{workers, solving, queued, fitting}` (`fitting`: how many mounts' models
  are being fitted or waiting to be); `:restarting` for the moment between a
  crash and its restart; `:down` when plate solving gave up after repeated
  crashes; `:not_started` when this server was updated in place (new code,
  no restart) and the queue was never started.
  """
  def status do
    cond do
      Process.whereis(__MODULE__) ->
        case call(:status) do
          %{} = s -> s
          _ -> :restarting
        end

      Process.whereis(Controller.Plates.Supervisor) ->
        :restarting

      child?(Controller.Plates.Supervisor) ->
        :down

      true ->
        :not_started
    end
  end

  defp child?(id) do
    Controller.Supervisor |> Supervisor.which_children() |> Enum.any?(&(elem(&1, 0) == id))
  catch
    :exit, _ -> false
  end

  @doc "Change how many plates solve at once."
  def set_workers(n) when is_integer(n) and n >= 1, do: call({:workers, n})

  @doc """
  Bring plate solving back after it gave up, or start it on a server that
  was updated in place (its supervisor children are only started at boot).
  """
  def restart do
    # Solve.solve/2's tasks, for the same updated-in-place server
    unless Process.whereis(Controller.Sky.Solve.Tasks),
      do: Supervisor.start_child(Controller.Supervisor, {Task.Supervisor, name: Controller.Sky.Solve.Tasks})

    case Supervisor.restart_child(Controller.Supervisor, Controller.Plates.Supervisor) do
      {:ok, _} -> :ok
      {:ok, _, _} -> :ok
      {:error, :running} -> :ok
      {:error, :not_found} -> started(Supervisor.start_child(Controller.Supervisor, Controller.Plates.Supervisor))
      {:error, reason} -> {:error, reason}
    end
  end

  defp started({:ok, _}), do: :ok
  defp started({:ok, _, _}), do: :ok
  defp started({:error, {:already_started, _}}), do: :ok
  defp started({:error, reason}), do: {:error, reason}

  defp call(msg, timeout \\ 5_000) do
    GenServer.call(__MODULE__, msg, timeout)
  catch
    :exit, _ -> {:error, :down}
  end

  # -- the process ----------------------------------------------------------------------------

  @impl true
  def init(opts) do
    Telescope.Events.tag("plates")
    Settings.subscribe()

    sessions =
      Store.load()
      |> Map.new(fn {mount, s} ->
        # solving when the last process stopped: nobody is solving them now
        {mount, %{s | plates: Enum.map(s.plates, &if(&1.state == :solving, do: %{&1 | state: :queued, started_ms: nil}, else: &1))}}
      end)

    state = %{
      sessions: sessions,
      # each mount's last model, and what is known of its fit (see "the fit" below)
      reports: %{},
      fits: %{},
      # the one fit running, and the mounts waiting for theirs, oldest first
      fit: nil,
      refits: [],
      fit_with: opts[:fit],
      fit_timeout: opts[:fit_timeout],
      running: %{},
      workers: opts[:workers] || Application.get_env(:controller, :plate_workers) || default_workers(),
      solve_timeout: opts[:solve_timeout] || Application.get_env(:controller, :plate_solve_timeout) || @solve_timeout
    }

    send(self(), :dispatch)
    # the models, from the plates on disk: asked for here, fitted in tasks
    {:ok, Enum.reduce(Map.keys(sessions), state, &refit(&2, &1))}
  end

  @impl true
  def handle_call({:add, mount, image, cap, opts}, _from, state) do
    now = DateTime.utc_now()
    format = Photo.format(image)
    photo_at = Photo.taken_at(image)

    cond do
      not is_map(cap) -> {:reply, {:error, :no_mount}, state}
      format not in [:jpeg, :pgm, :ppm, :fits] -> {:reply, {:error, :unsupported_image}, state}
      photo_at && DateTime.diff(cap.at, photo_at) > Keyword.get(opts, :max_age_s, @max_age_s) -> {:reply, {:error, :old_photo}, state}
      true ->
        session = current(state, mount)
        # re-zeroed since these plates: they count from a zero that is gone
        session = if session.plates != [] and session.home_at != cap.homed_at, do: new_session(mount, cap.homed_at), else: %{session | home_at: session.home_at || cap.homed_at}
        n = session.next
        file = Store.put_image(session.id, n, image, Photo.extension(format))

        {at, from} =
          cond do
            cap.tracking -> {cap.at, "encoders"}
            photo_at && DateTime.compare(photo_at, cap.at) != :gt -> {photo_at, "photo"}
            true -> {cap.at, "capture"}
          end

        plate = %{
          n: n,
          state: if(cap.moving, do: :failed, else: :queued),
          reason: if(cap.moving, do: "moving"),
          moving: cap.moving,
          file: file,
          captured_at: cap.at,
          photo_at: photo_at,
          at: at,
          time_from: from,
          enc: cap.enc,
          tracking: cap.tracking,
          homed_at: cap.homed_at,
          hint: cap[:hint],
          scale: opts[:scale],
          min_stars: opts[:min_stars],
          # a finder's solver gives up with its deadline, not a minute and a half after it
          timeout: opts[:timeout] || (opts[:finder] == true && (opts[:deadline] || finder_deadline())) || nil,
          downsample: opts[:downsample],
          nsigma: opts[:nsigma],
          finder: opts[:finder] == true,
          queued_at: now,
          started_ms: nil,
          attempts: 0,
          solution: nil
        }

        # a finder's own deadline, counted from here: someone is waiting on it
        if plate.finder and plate.state == :queued, do: Process.send_after(self(), {:deadline, mount, session.id, n}, opts[:deadline] || finder_deadline())
        session = %{session | plates: session.plates ++ [plate], next: n + 1, applied: false}
        Telescope.Events.emit(:plates, :added, %{id: mount, n: n, theta_ra: cap.enc.ra_deg, theta_dec: cap.enc.dec_deg, moving: cap.moving})
        {:reply, {:ok, n}, state |> put_session(session) |> dispatch()}
    end
  end

  def handle_call({:view, mount}, _from, state), do: {:reply, view(state, mount), state}

  def handle_call({:retry, mount, n}, _from, state) do
    case find(state, mount, n) do
      %{state: :failed, moving: false} ->
        state = update_plate(state, mount, n, &%{&1 | state: :queued, reason: nil, queued_at: DateTime.utc_now()})
        {:reply, :ok, state |> save_and_broadcast(mount) |> dispatch()}

      %{moving: true} ->
        {:reply, {:error, :moving}, state}

      nil ->
        {:reply, {:error, :not_found}, state}

      _ ->
        {:reply, {:error, :not_failed}, state}
    end
  end

  def handle_call({:remove, mount, n}, _from, state) do
    case find(state, mount, n) do
      nil ->
        {:reply, {:error, :not_found}, state}

      plate ->
        session = state.sessions[mount]
        state = stop_running(state, fn r -> r.sid == session.id and r.n == n end)
        Store.delete_image(session.id, plate.file)
        session = %{session | plates: Enum.reject(session.plates, &(&1.n == n)), applied: false}
        {:reply, :ok, state |> put_session(session) |> refit(mount) |> save_and_broadcast(mount) |> dispatch()}
    end
  end

  def handle_call({:clear, mount}, _from, state) do
    old = state.sessions[mount]
    state = if old, do: stop_running(state, fn r -> r.sid == old.id end), else: state
    session = new_session(mount, old && old.home_at)
    {:reply, :ok, state |> put_session(session) |> dispatch()}
  end

  def handle_call({:samples, mount}, _from, state) do
    site = Pointing.site()
    session = state.sessions[mount]
    solved = if session, do: Enum.filter(session.plates, &usable?/1), else: []

    if length(solved) < 2 do
      {:reply, {:error, :too_few}, state}
    else
      samples =
        Enum.map(solved, fn p ->
          {alt, az} = Astro.alt_az(p.solution.ra_deg, p.solution.dec_deg, site.lat, Astro.lst_deg(p.at, site.lon))

          %{"name" => "Photo #{p.n}", "at" => DateTime.to_iso8601(p.at), "theta_ra" => p.enc.ra_deg, "theta_dec" => p.enc.dec_deg,
            "ra_deg" => p.solution.ra_deg, "dec_deg" => p.solution.dec_deg, "alt" => alt, "az" => az}
        end)

      {:reply, {:ok, samples, session.home_at}, state}
    end
  end

  def handle_call({:applied, mount}, _from, state) do
    case state.sessions[mount] do
      nil -> {:reply, :ok, state}
      session -> {:reply, :ok, put_session(state, %{session | applied: true})}
    end
  end

  def handle_call(:status, _from, state) do
    queued = state.sessions |> Map.values() |> Enum.flat_map(& &1.plates) |> Enum.count(&(&1.state == :queued))
    {:reply, %{workers: state.workers, solving: map_size(state.running), queued: queued, fitting: length(fitting(state))}, state}
  end

  def handle_call({:workers, n}, _from, state), do: {:reply, :ok, dispatch(%{state | workers: n})}

  @impl true
  def handle_info(:dispatch, state) do
    for {mount, _} <- state.sessions, do: broadcast(state, mount)
    {:noreply, dispatch(state)}
  end

  def handle_info({ref, result}, state) when is_map_key(state.running, ref) do
    Process.demonitor(ref, [:flush])
    {r, running} = Map.pop(state.running, ref)
    Process.cancel_timer(r.timer)
    {:noreply, %{state | running: running} |> finish(r, result) |> dispatch()}
  end

  def handle_info({:DOWN, ref, :process, _, reason}, state) when is_map_key(state.running, ref) do
    {r, running} = Map.pop(state.running, ref)
    Process.cancel_timer(r.timer)
    Logger.warning("plate #{r.n} (#{r.mount}): solve crashed: #{inspect(reason)}")
    {:noreply, %{state | running: running} |> finish(r, {:error, :crashed}) |> dispatch()}
  end

  # the solver's own deadline should have ended it; this one does
  def handle_info({:give_up, ref}, state) when is_map_key(state.running, ref) do
    {r, running} = Map.pop(state.running, ref)
    Task.shutdown(r.task, :brutal_kill)
    {:noreply, %{state | running: running} |> finish(r, {:error, :timeout}) |> dispatch()}
  end

  # A finder's deadline. Not solved by now (still queued, or its solve still running): the solve is
  # stopped, the plate fails as "deadline" so whoever waits on it hears, and the queue moves on.
  def handle_info({:deadline, mount, sid, n}, state) do
    with %{id: ^sid} <- state.sessions[mount], %{state: waiting} when waiting in [:queued, :solving] <- find(state, mount, n) do
      Telescope.Events.emit(:plates, :deadline, %{id: mount, n: n})

      state
      |> stop_running(fn r -> r.sid == sid and r.n == n end)
      |> update_plate(mount, n, &%{&1 | state: :failed, reason: "deadline"})
      |> save_and_broadcast(mount)
      |> dispatch()
      |> then(&{:noreply, &1})
    else
      _ -> {:noreply, state}
    end
  end

  # the fit depends on where the scope stands and which way the axes turn
  def handle_info({:settings, key, _}, state) when key in ["site", "pointing"] do
    state = Enum.reduce(Map.keys(state.sessions), state, &refit(&2, &1))
    for {mount, _} <- state.sessions, do: broadcast(state, mount)
    {:noreply, state}
  end

  # the fit's task: its answer, its crash, its deadline. Whichever it is, the
  # next mount waiting gets its turn.
  def handle_info({ref, result}, %{fit: %{ref: ref} = f} = state) do
    Process.demonitor(ref, [:flush])
    Process.cancel_timer(f.timer)
    {:noreply, %{state | fit: nil} |> fitted(f, result) |> next_fit()}
  end

  def handle_info({:DOWN, ref, :process, _, reason}, %{fit: %{ref: ref} = f} = state) do
    Process.cancel_timer(f.timer)
    {:noreply, %{state | fit: nil} |> fitted(f, {:error, {:crashed, reason}}) |> next_fit()}
  end

  def handle_info({:fit_deadline, ref}, %{fit: %{ref: ref} = f} = state) do
    # an answer that came in as the deadline did is still an answer
    result =
      case Task.shutdown(f.task, :brutal_kill) do
        {:ok, answer} -> answer
        _ -> {:error, :timeout}
      end

    {:noreply, %{state | fit: nil} |> fitted(f, result) |> next_fit()}
  end

  def handle_info(_, state), do: {:noreply, state}

  # -- the queue --------------------------------------------------------------------------------

  defp dispatch(state) do
    state = make_way(state)
    free = state.workers - map_size(state.running)

    if free <= 0 do
      state
    else
      state |> queue() |> Enum.take(free) |> Enum.reduce(state, fn {mount, plate}, acc -> start(acc, mount, plate) end)
    end
  end

  # A finder never waits for a worker. With every worker busy and a finder queued, one solve that
  # is not a finder's is stopped and its plate queued again where it was (solved from the start,
  # after the finder): never more solves at once than the machine was given workers for.
  defp make_way(state) do
    with true <- state.workers - map_size(state.running) <= 0,
         true <- Enum.any?(queue(state), fn {_, p} -> p[:finder] == true end),
         %{} = r <- state.running |> Map.values() |> Enum.find(&keeper?(state, &1)) do
      state
      |> stop_running(&(&1 == r))
      |> update_plate(r.mount, r.n, &%{&1 | state: :queued, started_ms: nil})
      |> save_and_broadcast(r.mount)
    else
      _ -> state
    end
  end

  # a solve that may make way: its plate is still there, and is not a finder itself
  defp keeper?(state, r) do
    case find(state, r.mount, r.n) do
      %{} = plate -> plate[:finder] != true
      nil -> false
    end
  end

  # every queued plate, finders first, then oldest first, across mounts
  defp queue(state) do
    for {mount, s} <- state.sessions, p <- s.plates, p.state == :queued do
      {mount, p}
    end
    |> Enum.sort_by(fn {_, p} -> {p[:finder] != true, DateTime.to_unix(p.queued_at, :microsecond), p.n} end)
  end

  defp start(state, mount, plate) do
    session = state.sessions[mount]
    path = Store.image_path(session.id, plate.file)
    opts =
      [hint: plate.hint, scale: plate[:scale] || scale(session), timeout: plate[:timeout] || state.solve_timeout, sky: %{at: plate.at, site: Pointing.site()}] ++
        if(plate[:min_stars], do: [min_stars: plate.min_stars], else: []) ++
        if(plate[:downsample], do: [downsample: plate.downsample], else: []) ++
        if(plate[:nsigma], do: [nsigma: plate.nsigma], else: [])

    task =
      Task.Supervisor.async_nolink(@tasks, fn ->
        case File.read(path) do
          {:ok, bytes} -> Solve.run(bytes, opts)
          {:error, e} -> {:error, {:image, e}}
        end
      end)

    timer = Process.send_after(self(), {:give_up, task.ref}, (plate[:timeout] || state.solve_timeout) + @grace_ms)
    run = %{mount: mount, sid: session.id, n: plate.n, task: task, timer: timer}

    state
    |> Map.update!(:running, &Map.put(&1, task.ref, run))
    |> update_plate(mount, plate.n, &%{&1 | state: :solving, started_ms: System.system_time(:millisecond), attempts: &1.attempts + 1})
    |> save_and_broadcast(mount)
  end

  defp finish(state, r, result) do
    session = state.sessions[r.mount]

    # forgotten, or started over, while it solved: nothing to update
    if session && session.id == r.sid && find(state, r.mount, r.n) do
      state =
        update_plate(state, r.mount, r.n, fn p ->
          case result do
            {:ok, sol} ->
              keep = Map.take(sol, [:ra_deg, :dec_deg, :width_deg, :height_deg, :rotation_deg, :parity, :seconds, :solver, :stars, :pixscale_arcsec])
              %{p | state: :solved, reason: nil, solution: keep}

            {:error, reason} ->
              %{p | state: :failed, reason: reason_word(reason)}
          end
        end)

      Telescope.Events.emit(:plates, :solved, %{id: r.mount, n: r.n, ok: match?({:ok, _}, result)})
      state |> refit(r.mount) |> save_and_broadcast(r.mount)
    else
      state
    end
  end

  defp stop_running(state, pick) do
    {gone, keep} = Enum.split_with(state.running, fn {_, r} -> pick.(r) end)

    for {_, r} <- gone do
      Process.cancel_timer(r.timer)
      Task.shutdown(r.task, :brutal_kill)
    end

    %{state | running: Map.new(keep)}
  end

  @doc false
  def reason_word(r) when r in [:too_few_stars, :no_solution, :below_horizon, :timeout, :no_solver, :unsupported_image, :crashed], do: Atom.to_string(r)
  def reason_word(r), do: r |> inspect() |> String.slice(0, 120)

  # -- sessions and the fit -----------------------------------------------------------------------

  defp current(state, mount), do: state.sessions[mount] || new_session(mount, nil)

  defp new_session(mount, home_at) do
    now = DateTime.utc_now()
    %{id: Store.new_id(mount, now), mount: mount, home_at: home_at, next: 1, applied: false, created_at: now, plates: []}
  end

  defp put_session(state, session) do
    state = %{state | sessions: Map.put(state.sessions, session.mount, session)}
    state |> refit(session.mount) |> save_and_broadcast(session.mount)
  end

  defp save_and_broadcast(state, mount) do
    if s = state.sessions[mount] do
      try do
        Store.save(s)
      rescue
        e -> Logger.error("plates: could not save #{s.id}: #{Exception.message(e)}")
      end
    end

    broadcast(state, mount)
    state
  end

  defp broadcast(state, mount), do: Telescope.broadcast("plates:" <> mount, {:plates, mount, view(state, mount)})

  defp find(state, mount, n), do: state.sessions[mount] && Enum.find(state.sessions[mount].plates, &(&1.n == n))

  defp update_plate(state, mount, n, fun) do
    session = state.sessions[mount]
    plates = Enum.map(session.plates, &if(&1.n == n, do: fun.(&1), else: &1))
    %{state | sessions: Map.put(state.sessions, mount, %{session | plates: plates})}
  end

  defp usable?(p), do: p.state == :solved and not p.moving and is_map(p.solution)

  # -- the fit: in a task, one at a time, never in this process ----------------------------------
  #
  # state.reports[mount]  the last model that landed
  # state.fits[mount]     %{asked, plates, dropped}: what the newest fit asked for was made
  #                       from, the plates the last model was fitted from, and why the
  #                       last fit was dropped if it was (:failed, :timeout)
  # state.fit             the one fit running
  # state.refits          mounts waiting for theirs, oldest first, each one once

  # a fit still running after this long is stopped (ms)
  @fit_timeout 30_000

  # Ask for this mount's model again, from its plates as they are now.
  # Nothing is computed here. Asking twice for the same plates is asking once,
  # and a mount already waiting stays waiting once, however many plates
  # arrive: its fit takes them all when its turn comes.
  defp refit(state, mount) do
    inputs = fit_inputs(state.sessions[mount])
    known = state.fits[mount]

    cond do
      # nothing solved (or started over): no model, and a fit under way is of plates that are gone
      inputs == nil ->
        state |> drop_fit(mount) |> next_fit()

      # asked already, of exactly these plates, and it landed or is on its way. One that was
      # dropped is not tried again by itself (it would fail the same way, all night); the next
      # thing done with the photos (another one, a retry, Use This Alignment) asks again.
      known != nil and known.asked == inputs and (known.dropped == nil or mount in fitting(state)) ->
        state

      true ->
        # another session's model (zeroed again) is not this one's last model
        state = if known != nil and known.asked.sid != inputs.sid, do: drop_fit(state, mount), else: state
        known = Map.put(state.fits[mount] || %{plates: [], dropped: nil}, :asked, inputs)
        waiting = if mount in state.refits, do: state.refits, else: state.refits ++ [mount]
        next_fit(%{state | fits: Map.put(state.fits, mount, known), refits: waiting})
    end
  end

  # what a fit is made from: the session's solved plates, where the scope stands, which way the axes turn
  defp fit_inputs(nil), do: nil

  defp fit_inputs(session) do
    case Enum.filter(session.plates, &usable?/1) do
      [] ->
        nil

      used ->
        samples = for p <- used, do: %{theta_ra: p.enc.ra_deg, theta_dec: p.enc.dec_deg, ra_deg: p.solution.ra_deg, dec_deg: p.solution.dec_deg, at: p.at}
        %{sid: session.id, plates: Enum.map(used, & &1.n), samples: samples, site: Pointing.site(), signs: Pointing.pointing()}
    end
  end

  # the next mount waiting, when no fit is running
  defp next_fit(%{fit: nil, refits: [mount | waiting]} = state) do
    %{asked: inputs} = state.fits[mount]
    # from the last model: one descent instead of a search of the whole sky (`Model.fit/4`)
    near = state.reports[mount] && state.reports[mount][:params]
    mod = state.fit_with || Application.get_env(:controller, :plate_fit) || Polar
    timeout = state.fit_timeout || Application.get_env(:controller, :plate_fit_timeout) || @fit_timeout

    # monitored, not linked: a fit that falls over is a message here, never the end of the queue
    task = Task.Supervisor.async_nolink(@tasks, fn -> mod.fit(inputs.samples, site: inputs.site, signs: inputs.signs, near: near) end)
    timer = Process.send_after(self(), {:fit_deadline, task.ref}, timeout)
    %{state | fit: %{ref: task.ref, task: task, timer: timer, mount: mount, inputs: inputs, timeout: timeout}, refits: waiting}
  end

  defp next_fit(state), do: state

  # A fit's answer, or what became of it. A good one is the model from now on.
  # Anything else is dropped: the last model stays and the view says so.
  defp fitted(state, f, result) do
    session = state.sessions[f.mount]

    cond do
      # started over or zeroed again while it ran: a model of plates that are gone
      session == nil or session.id != f.inputs.sid or state.fits[f.mount] == nil ->
        state

      match?({:ok, %{}}, result) ->
        {:ok, report} = result
        state = %{state | reports: Map.put(state.reports, f.mount, report), fits: Map.update!(state.fits, f.mount, &%{&1 | plates: f.inputs.plates, dropped: nil})}
        broadcast(state, f.mount)
        state

      true ->
        why = if result == {:error, :timeout}, do: :timeout, else: :failed
        said = if why == :timeout, do: "ran past #{f.timeout} ms and was stopped", else: "failed (#{result |> inspect() |> String.slice(0, 200)})"
        Logger.warning("plates: the fit for #{f.mount} #{said}; the last model stays")
        Telescope.Events.emit(:plates, :fit_dropped, %{id: f.mount, why: Atom.to_string(why)})
        state = %{state | fits: Map.update!(state.fits, f.mount, &%{&1 | dropped: why})}
        broadcast(state, f.mount)
        state
    end
  end

  # forget this mount's model, and stop fitting it
  defp drop_fit(state, mount) do
    state =
      case state.fit do
        %{mount: ^mount} = f ->
          Process.cancel_timer(f.timer)
          Task.shutdown(f.task, :brutal_kill)
          %{state | fit: nil}

        _ ->
          state
      end

    %{state | reports: Map.delete(state.reports, mount), fits: Map.delete(state.fits, mount), refits: List.delete(state.refits, mount)}
  end

  # the mounts whose model is behind their plates: being fitted, or waiting to be
  defp fitting(state), do: Enum.uniq(if(state.fit, do: [state.fit.mount], else: []) ++ state.refits)

  # one calm line while the last fit is one that was dropped
  defp fit_notice(%{dropped: why}, report) when why != nil do
    if(why == :timeout, do: "The fit took too long and was stopped.", else: "The fit failed.") <>
      if(report, do: " The last model is in use.", else: " There is no model yet.")
  end

  defp fit_notice(_, _), do: nil

  # the field of the plates so far, with room either side; the default otherwise
  defp scale(session) do
    case for(%{state: :solved, solution: %{width_deg: w}} <- session.plates, is_number(w), do: w) do
      [] -> {0.2, 3.0}
      ws -> {min(0.2, Enum.min(ws) / 2), max(3.0, Enum.max(ws) * 2)}
    end
  end

  defp view(state, mount) do
    session = state.sessions[mount]
    report = state.reports[mount]

    if session == nil do
      %{mount: mount, session: nil, plates: [], report: nil, applied: false, home_at: nil, workers: state.workers, fitting: false, fit_notice: nil}
    else
      order = state |> queue() |> Enum.map(fn {m, p} -> {m, p.n} end)
      known = state.fits[mount]
      # by the plates the model was fitted from: with a fit under way, not every solved one
      residuals = if report && known, do: Enum.zip(known.plates, report.residuals_arcmin) |> Map.new(), else: %{}

      plates =
        Enum.map(session.plates, fn p ->
          Map.merge(p, %{
            ahead: if(p.state == :queued, do: Enum.find_index(order, &(&1 == {mount, p.n}))),
            residual_arcmin: residuals[p.n]
          })
        end)

      %{mount: mount, session: session.id, plates: plates, report: report, applied: session.applied, home_at: session.home_at, workers: state.workers,
        fitting: mount in fitting(state), fit_notice: fit_notice(known, report)}
    end
  end
end
