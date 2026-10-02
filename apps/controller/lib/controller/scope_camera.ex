defmodule Controller.ScopeCamera do
  @moduledoc """
  The camera in the telescope's focuser (a USB camera like the SVBONY SV105
  plugged into the box). It does three jobs, in the order you need them at
  night:

    1. **Focus.** With `live(true)` it takes frame after frame, measures the
       stars in each (how many, how sharp: the half-flux radius), and keeps
       the last minute of that so a page can show whether turning the
       focuser is helping.
    2. **Say where the telescope points.** `grab/1` takes one frame (stacked
       if asked) for the plate solver.
    3. **Be looked at.** The latest frame, brightened so faint stars show,
       and a close-up of the brightest star, for the phone.

  It finds the camera on its own and notices one being plugged in (every
  3 s while there's none). With no camera and `config :controller,
  :scope_camera, sim: true` (the Mac in development), it uses the simulated
  camera on the simulated mount.

  Frames are taken by a task, one at a time, so a camera that hangs never
  hangs this process; its deadline kills it. Everything a page needs is
  broadcast on `"scope_camera"` as `{:scope_camera, status}`; the frame's
  bytes stay in `:persistent_term` for `latest/0`.

  Knobs (also on the page): `exposure_ms`, `gain`, `stack` (frames averaged
  per picture), kept in Settings under `"scope_camera"`.

  With `keep(true)` every frame it takes is also kept: handed to the frames
  pipeline (`Controller.Frames`: the box's card, then the Mac), never
  waited on. A frame the pipeline has no room for is dropped and counted
  on the Queues page, and the camera carries on.
  """
  use GenServer
  require Logger

  alias Controller.ScopeCamera.{Defects, Device, Header, Image, Sim, Stream}
  alias Controller.Settings

  @scan_ms 3_000
  @seq_block 50
  @history 90
  @defaults %{"exposure_ms" => 500, "gain" => 50, "stack" => 1}

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  What a page shows: the camera, the settings, live or not, the focus
  readings, the last error, and `node`, the machine it's on.

  Every call that acts on the camera takes the machine last (this one by
  default), so a page on the Mac drives the camera plugged into a box: it
  shows the status it heard (`find/0`, `prefer/2`) and sends its taps to
  that status's `node`.
  """
  def status(node \\ node()) do
    GenServer.call(server(node), :status, 2_000)
  catch
    :exit, _ -> %{camera: nil, down: true, node: node}
  end

  @doc """
  The camera a page should show, across the cluster: a real camera before
  the simulator, the simulator before none, this machine's when it's a tie.
  So the Mac shows the camera plugged into the box, not its own stand-in.
  """
  def find do
    local = status()

    Node.list()
    |> Enum.map(fn n -> n |> status() |> Map.put_new(:node, n) end)
    |> Enum.reduce(local, fn st, best -> if rank(st) > rank(best), do: st, else: best end)
  end

  @doc """
  Of the status a page has and one just heard (statuses are broadcast across
  the cluster, so a page on the Mac hears the box's and the Mac's own), the
  one to show: the same machine's news always, another machine's only when
  its camera is better (`find/0`'s order), so the page doesn't flicker.
  """
  def prefer(old, new) do
    if Map.get(old || %{}, :node) == Map.get(new, :node) or rank(new) > rank(old), do: new, else: old
  end

  # a real camera, the simulator, none
  defp rank(%{camera: nil}), do: 0
  defp rank(%{sim: true}), do: 1
  defp rank(%{camera: _}), do: 2
  defp rank(_), do: 0

  @doc "Whether a status is a camera on another machine (its pictures come through this one)."
  def remote?(cam), do: Map.get(cam || %{}, :node, node()) != node()

  @doc "Where a page gets a camera's latest picture (`seq` makes each new one a new address)."
  def src(cam, seq), do: "/cameras/telescope/frame.png?" <> URI.encode_query([t: seq] ++ on(cam))

  @doc "Where a page gets one of the last frames by number."
  def src_numbered(cam, seq), do: "/cameras/telescope/frames/#{seq}/frame.png" <> if(remote?(cam), do: "?" <> URI.encode_query(on(cam)), else: "")

  defp on(cam), do: if(remote?(cam), do: [node: to_string(cam.node)], else: [])

  @doc "A connected machine by name, from a page's address (never makes an atom from it)."
  def node_named(nil), do: node()
  def node_named(name), do: Enum.find([node() | Node.list()], node(), &(to_string(&1) == name))

  defp server(node) when node == node(), do: __MODULE__
  defp server(node), do: {__MODULE__, node}

  @doc "The latest frame: `%{png, star_png, at, focus, stars, stats, w, h}`, or nil."
  def latest, do: :persistent_term.get({__MODULE__, :latest}, nil)

  @doc "Keep taking frames (for focusing), or stop."
  def live(on?, node \\ node()) when is_boolean(on?), do: GenServer.call(server(node), {:live, on?})

  @doc "Change `exposure_ms:`, `gain:`, `stack:`; they're kept, and set on the camera."
  def set(opts, node \\ node()), do: GenServer.call(server(node), {:set, Map.new(opts)}, 10_000)

  @doc """
  One frame now, for the solver: `{:ok, %{pgm, at, focus, stars}}` or an
  error. Waits for a frame already being taken, then takes its own.
  Options override the settings for this frame (`stack:`, `exposure_ms:`);
  `mount:` says which simulated mount a simulated camera is on.
  """
  def grab(opts \\ []) do
    GenServer.call(__MODULE__, {:grab, opts}, 120_000)
  catch
    :exit, {:timeout, _} -> {:error, :timeout}
    :exit, _ -> {:error, :down}
  end

  def subscribe, do: Telescope.subscribe("scope_camera")

  # the camera is the first step of the frames pipeline: its numbers go on the
  # Queues page like any queue's, every second
  @report_ms 1_000

  @doc """
  Real video on the phone instead of pictures: the camera goes to `Video`
  (H.264 on the Pi's own encoder, HLS, which Safari plays), and comes back
  for pictures when video stops. A camera is read by one thing at a time, so
  while video runs, pictures (and finding where it points) wait.
  """
  def video(on?, node \\ node()) when is_boolean(on?), do: GenServer.call(server(node), {:video, on?}, 15_000)

  @doc "One of the last #{20} frames by number: `{:ok, record, png}`, or `:error` once it's gone."
  def frame(seq, node \\ node())

  def frame(seq, node) when node != node() do
    :erpc.call(node, __MODULE__, :frame, [seq], 5_000)
  catch
    _, _ -> :error
  end

  def frame(seq, _node) do
    case :ets.lookup(__MODULE__.Recent, seq) do
      [{^seq, record, png}] -> {:ok, record, png}
      _ -> :error
    end
  rescue
    ArgumentError -> :error
  end

  @doc "Keep every frame taken (to the card, then the Mac), or stop keeping them. Remembered."
  def keep(on?, node \\ node()) when is_boolean(on?), do: GenServer.call(server(node), {:keep, on?})

  @doc "Use the simulated camera when no real one is plugged in (or stop)."
  def simulate(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:simulate, on?})

  # -- the process --------------------------------------------------------------------------

  @impl true
  def init(opts) do
    Process.flag(:trap_exit, true)
    # the last few frames' pictures, for a page per frame; readable by any process
    :ets.new(__MODULE__.Recent, [:named_table, :set, :protected, read_concurrency: true])
    Device.load_driver()
    send(self(), :scan)
    Process.send_after(self(), :report, @report_ms)

    {:ok,
     %{
       camera: nil,
       sim: Keyword.get(opts, :sim, config(:sim, false)),
       settings: Map.merge(@defaults, Settings.get("scope_camera", %{})),
       live: false,
       task: nil,
       waiting: [],
       history: [],
       error: nil,
       controls: %{},
       # what the camera is set to now (a grab can ask for other than the settings)
       applied: nil,
       max_exposure_ms: nil,
       video: false,
       keep: Settings.get("scope_camera_keep", false),
       # specks that are the sensor's, learned across pointings and kept (Defects)
       defects: Defects.new(Settings.get("scope_camera_defects", [])),
       # the last minute of frames: how long taking one took (the grab, then measuring it here)
       meter: Queues.Meter.new(),
       parts: [],
       failed: 0,
       # every frame taken or failed gets the next number, never reused across restarts
       # (the count is saved every 50; after a restart it carries on past the last save)
       seq: next_block(),
       frames: [],
       kept: 0,
       not_kept: 0
     }}
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, public(s), s}
  def handle_call({:simulate, on?}, _from, s), do: {:reply, :ok, scan(%{s | sim: on?})}

  def handle_call({:video, true}, _from, %{camera: %{path: path}} = s) do
    # one reader at a time: the picture stream lets the camera go first
    Stream.stop()

    reply =
      safe(fn ->
        Video.select(path)
        Video.start(quality: Settings.get("video_quality", "auto"), fps: Settings.get("video_fps", 30))
      end)

    case reply do
      {:error, e} -> {:reply, {:error, e}, publish(%{s | error: "Video didn't start: #{inspect(e)}"})}
      _ -> {:reply, :ok, publish(%{s | video: true, live: false})}
    end
  end

  def handle_call({:video, true}, _from, s), do: {:reply, {:error, :no_real_camera}, s}

  def handle_call({:video, false}, _from, s) do
    if s.video, do: safe(fn -> Video.stop() end)
    {:reply, :ok, publish(%{s | video: false})}
  end

  def handle_call({:keep, on?}, _from, s) do
    Settings.put("scope_camera_keep", on?)
    {:reply, :ok, publish(%{s | keep: on?})}
  end

  def handle_call({:live, on?}, _from, s) do
    s = %{s | live: on?}
    {:reply, :ok, s |> maybe_next() |> publish()}
  end

  def handle_call({:set, changes}, _from, s) do
    settings =
      Enum.reduce(changes, s.settings, fn
        {k, v}, acc when k in [:exposure_ms, :gain, :stack] and is_number(v) -> Map.put(acc, Atom.to_string(k), v)
        _, acc -> acc
      end)

    Settings.put("scope_camera", settings)
    s = %{s | settings: settings} |> apply_settings()
    {:reply, :ok, publish(s)}
  end

  def handle_call({:grab, opts}, from, s) do
    cond do
      s.camera == nil -> {:reply, {:error, :no_camera}, s}
      s.video -> {:reply, {:error, :showing_video}, s}
      true -> {:noreply, %{s | waiting: s.waiting ++ [{from, opts}]} |> maybe_next()}
    end
  end

  @impl true
  def handle_info(:report, s) do
    Process.send_after(self(), :report, @report_ms)
    if s.camera, do: Telescope.broadcast("queues", {:queue, node(), "camera", step_stats(s)})
    {:noreply, s}
  end

  def handle_info(:scan, s) do
    Process.send_after(self(), :scan, @scan_ms)
    {:noreply, scan(s)}
  end

  def handle_info({ref, result}, %{task: %{ref: ref} = task} = s) do
    Process.demonitor(ref, [:flush])
    s = %{s | task: nil} |> taken(task, result)
    {:noreply, s |> maybe_next() |> publish()}
  end

  def handle_info({:DOWN, ref, :process, _, reason}, %{task: %{ref: ref} = task} = s) do
    s = %{s | task: nil} |> taken(task, {:error, {:crashed, reason}})
    {:noreply, s |> maybe_next() |> publish()}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- finding the camera --------------------------------------------------------------------

  defp scan(s) do
    found = safe_list()

    camera =
      cond do
        s.camera && s.camera != :sim && Enum.any?(found, &(&1.id == s.camera.id)) -> s.camera
        found != [] -> hd(found)
        s.sim && sim_mount(nil) -> :sim
        true -> nil
      end

    cond do
      camera == s.camera ->
        s

      camera == nil ->
        Logger.info("scope camera: unplugged")
        Telescope.Events.emit(:scope_camera, :gone, %{})
        publish(%{s | camera: nil, error: nil})

      true ->
        camera =
          with %{path: path} <- camera do
            modes = safe(fn -> Device.modes(path) end) || []
            best = Device.best_mode(modes)
            Map.merge(camera, %{mode: best, info: safe(fn -> Device.info(path) end) || %{}})
          end

        Logger.info("scope camera: #{describe(camera)}")
        Telescope.Events.emit(:scope_camera, :found, %{name: describe(camera)})
        %{s | camera: camera, error: nil} |> apply_settings() |> maybe_next() |> publish()
    end
  end

  defp safe_list do
    Device.list()
  rescue
    _ -> []
  end

  # the simulated mount the simulated camera sits on: the one asked for, else the first
  defp sim_mount(nil), do: Enum.find_value(safe(fn -> Mount.list() end) || [], fn m -> if Mount.simulated?(m.id), do: m.id end)
  defp sim_mount(id), do: id

  defp apply_settings(%{camera: %{path: path}} = s) do
    wanted = %{exposure_ms: s.settings["exposure_ms"], gain: s.settings["gain"]}
    safe(fn -> Device.set(path, Map.to_list(wanted)) end)
    %{s | applied: wanted, controls: safe(fn -> Device.controls(path) end) || %{}, max_exposure_ms: safe(fn -> Device.max_exposure_ms(path) end)}
  end

  defp apply_settings(s), do: s

  # -- taking frames ---------------------------------------------------------------------------

  # one frame at a time: someone waiting for one comes first, then the live view
  defp maybe_next(%{task: nil, camera: camera, video: false} = s) when camera != nil do
    case s.waiting do
      [{from, opts} | rest] -> start(%{s | waiting: rest}, {:grab, from}, opts)
      [] -> if s.live, do: start(s, :live, []), else: s
    end
  end

  defp maybe_next(s), do: s

  defp start(s, why, opts) do
    camera = s.camera
    settings = s.settings
    stack = Keyword.get(opts, :stack, settings["stack"])
    # no longer than the camera goes: the deadline is sized from it
    exposure = Keyword.get(opts, :exposure_ms, settings["exposure_ms"])
    exposure = if s.max_exposure_ms, do: min(exposure, s.max_exposure_ms), else: exposure
    wanted = %{exposure_ms: exposure, gain: Keyword.get(opts, :gain, settings["gain"])}
    at = DateTime.utc_now()

    asked = %{
      why: if(why == :live, do: "live view", else: "picture"),
      exposure_ms: exposure,
      gain: wanted.gain,
      stack: stack,
      mode: mode_words(camera)
    }

    # the scope this camera is on: the one asked about, else this box's own
    mount_id = opts[:mount] || with(%{id: id} <- Mount.default(Mount.local_list()), do: id)
    known = header_known(s, camera, wanted)
    defects = s.defects

    task =
      Task.Supervisor.async_nolink(Controller.ScopeCamera.Tasks, fn ->
        # a grab that asks for other than what the camera is set to sets it first,
        # and lets the frames still made at the old settings go by: the SV105C
        # keeps sending the old exposure for three frames after a change
        # (measured on the box: 1.2 ↔ 2.5 ms in daylight, skip 1 and 2 still old)
        changed? = wanted != s.applied
        if changed?, do: set_camera(camera, wanted)

        t0 = System.monotonic_time(:millisecond)
        mount_start = Header.snapshot(mount_id)


        # live view takes the next frame; a picture waits for light from after it was asked for
        with {:ok, pgm} <- take(camera, stack: stack, exposure_ms: exposure, mount: opts[:mount], skip: if(changed?, do: 3, else: 0), fresh: why != :live) do
          t1 = System.monotonic_time(:millisecond)
          ended = DateTime.utc_now()
          mount_end = Header.snapshot(mount_id)
          frame = analyse(pgm, defects)

          context =
            mount_id
            |> Header.context(at)
            |> Map.merge(known)
            |> Map.merge(%{ended_at: ended, mount: mount_id && %{id: mount_id, start: mount_start, end: mount_end}})

          {:ok, pgm, Map.merge(frame, %{timing: %{grab_ms: t1 - t0, analyse_ms: System.monotonic_time(:millisecond) - t1}, context: context})}
        end
      end)

    %{s | task: %{ref: task.ref, why: why, at: at, started: Queues.Meter.now(), asked: asked}, applied: wanted}
  end

  defp set_camera(%{path: path}, wanted), do: Device.set(path, Map.to_list(wanted))
  defp set_camera(_, _), do: :ok

  defp take(:sim, opts), do: Sim.grab(sim_mount(opts[:mount]), Keyword.put(opts, :defocus, Settings.get("sim_defocus", 0.0)))
  defp take(%{path: path} = camera, opts) do
    with {:ok, pgm, _} <- Stream.frame(path, Map.get(camera, :mode), Keyword.take(opts, [:stack, :exposure_ms, :skip, :fresh])), do: {:ok, pgm}
  end

  @doc false
  # what a page and the solver want from a frame; a speck on a known defect isn't a star
  def analyse(pgm, defects \\ Defects.new()) do
    {:ok, img} = Image.from_pgm(pgm)
    stats = Image.stats(img)
    found = Image.find(img, stats: stats)
    {stars, specks} = Defects.split(defects, found.stars)
    found = %{found | stars: stars, rejected: Enum.map(specks, &%{x: &1.x, y: &1.y, why: :defect}) ++ found.rejected}
    focus = Image.focus(stars)

    star_png =
      case Enum.find(stars, &(&1.peak < 250)) || List.first(stars) do
        nil -> nil
        st -> img |> Image.crop(st.x, st.y, 40) |> Image.stretch(stats: stats, lo: stats.background, hi: max(st.peak, stats.background + 8)) |> Image.png()
      end

    verdict = Image.verdict(stats, stars)

    %{
      png: Image.png(img, curve: Image.curve(stats)),
      star_png: star_png,
      focus: focus,
      stars: Enum.take(stars, 10),
      stats: stats,
      verdict: verdict,
      w: img.w,
      h: img.h,
      detail: Image.detail(img, stats),
      # what a page can draw over the picture: the stars kept, what was ignored and why, the border
      marks: %{
        stars: stars |> Enum.take(20) |> Enum.map(&%{x: round(&1.x), y: round(&1.y), hfr: Float.round(&1.hfr * 1.0, 1)}),
        rejected: Enum.map(found.rejected, &%{x: round(&1.x), y: round(&1.y), why: &1.why}),
        border: found.border
      }
    }
  end

  defp taken(s, %{started: started} = task, result) do
    now = Queues.Meter.now()

    s =
      case result do
        {:ok, pgm, %{timing: t}} -> %{s | meter: Queues.Meter.add(s.meter, started, now, 0, byte_size(pgm)), parts: Enum.take([t | s.parts], 60)}
        _ -> %{s | meter: Queues.Meter.add(s.meter, started, now, 0, 0), failed: s.failed + 1}
      end

    seq = s.seq + 1
    if rem(seq, @seq_block) == 0, do: Settings.put("scope_camera_seq", seq)
    record = record(seq, task, result, now - started)
    taken_(%{s | seq: seq, frames: Enum.take([record | s.frames], 20)}, Map.put(task, :record, record), result)
  end

  defp next_block do
    start = Settings.get("scope_camera_seq", 0) + @seq_block
    Settings.put("scope_camera_seq", start)
    start
  end

  # what a frame was, for the page, the kept file and whoever debugs it later
  defp record(seq, %{at: at, asked: asked}, result, took_ms) do
    base = Map.merge(asked, %{seq: seq, at: at, took_ms: took_ms})

    case result do
      {:ok, _pgm, frame} ->
        Map.merge(base, %{
          ok: true,
          grab_ms: frame.timing.grab_ms,
          measure_ms: frame.timing.analyse_ms,
          size: "#{frame.w}×#{frame.h}",
          w: frame.w,
          h: frame.h,
          background: frame.stats.background,
          noise: Float.round(frame.stats.noise * 1.0, 1),
          max: frame.stats.max,
          saturated_pct: Float.round(frame.stats.saturated * 100, 1),
          stars: frame.focus.stars,
          hfr_px: frame.focus.hfr && Float.round(frame.focus.hfr * 1.0, 2),
          verdict: frame.verdict,
          detail: frame[:detail],
          marks: frame[:marks]
        })

      {:error, reason} ->
        Map.merge(base, %{ok: false, error: words(reason)})
    end
  end

  # what the header says about the camera that the camera process already knows
  defp header_known(s, camera, wanted) do
    controls = Map.new(s.controls, fn {k, c} -> {k, c[:value]} end)
    controls = if wanted[:exposure_ms], do: Map.put(controls, "exposure_time_absolute", round(wanted.exposure_ms * 10)), else: controls
    controls = if wanted[:gain] && Map.has_key?(controls, "gain"), do: Map.put(controls, "gain", wanted.gain), else: controls
    mode = if is_map(camera), do: camera[:mode]

    %{
      camera_name: describe_name(camera),
      camera_info: if(is_map(camera), do: camera[:info] || %{}, else: %{}),
      controls: controls,
      mode_words: mode_words(camera),
      format: mode && mode.format,
      capture_size: mode && mode.size,
      fps: mode && mode[:fps]
    }
  end

  defp describe_name(:sim), do: "Simulated camera"
  defp describe_name(%{name: name}), do: name
  defp describe_name(_), do: nil

  defp mode_words(%{mode: %{format: f, size: {w, h}}}), do: "#{if f == "mjpeg", do: "JPEG", else: "raw"} #{w}×#{h}"
  defp mode_words(:sim), do: "simulated"
  defp mode_words(_), do: "camera default"

  # a speck seen at the same place from three pointings is the sensor's: remember it for good
  defp learn_defects(s, frame) do
    pointing = Defects.pointing(get_in(frame, [:context, :mount, :start]))

    case Defects.learn(s.defects, get_in(frame, [:marks, :stars]) || [], pointing) do
      {d, true} ->
        Logger.info("scope camera: #{length(Defects.cells(d))} sensor defects known (a speck at the same place from three pointings)")
        Settings.put("scope_camera_defects", Defects.cells(d))
        %{s | defects: d}

      {d, false} ->
        %{s | defects: d}
    end
  end

  defp taken_(s, %{why: why, at: at, record: record}, result) do
    case result do
      {:ok, pgm, frame} ->
        frame = Map.merge(frame, %{at: at, record: record})
        :persistent_term.put({__MODULE__, :latest}, frame)
        :ets.insert(__MODULE__.Recent, {record.seq, record, frame.png})
        :ets.delete(__MODULE__.Recent, record.seq - 20)
        reply(why, {:ok, Map.merge(frame, %{pgm: pgm})})
        point = %{at: at, hfr: frame.focus.hfr, stars: frame.focus.stars}

        %{s | error: nil, history: Enum.take([point | s.history], @history)}
        |> learn_defects(frame)
        |> keep_frame(pgm, record, frame[:context] || %{})

      {:error, reason} ->
        reply(why, {:error, reason})

        cond do
          # it dropped off the USB bus (a hub reset takes everything on it for a couple of
          # seconds): forget it, and live view carries on when the scan finds it again
          gone?(s.camera) ->
            Logger.warning("scope camera: #{inspect(reason)}; it dropped off the USB bus")
            %{s | camera: nil, error: "The camera dropped off the USB bus; carrying on when it's back"}

          # the size and format it said it had didn't work: its own default next time
          match?(%{mode: m} when m != nil, s.camera) ->
            Logger.warning("scope camera: #{inspect(reason)} in #{inspect(s.camera.mode)}; using the camera's own format")
            %{s | camera: %{s.camera | mode: nil}}

          true ->
            Logger.warning("scope camera: #{inspect(reason)}")
            # a camera that keeps failing stops being asked, until someone asks again
            %{s | error: words(reason), live: false}
        end
    end
  end

  defp gone?(%{path: "/dev/" <> _ = path}), do: not File.exists?(path)
  defp gone?(_), do: false

  # every frame taken, when keeping: to the frames pipeline, never waited on
  defp keep_frame(%{keep: false} = s, _pgm, _record, _context), do: s

  defp keep_frame(s, pgm, record, context) do
    case Controller.Frames.keep(%{pgm: pgm, record: record, context: context}) do
      :ok -> %{s | kept: s.kept + 1}
      _ -> %{s | not_kept: s.not_kept + 1}
    end
  end

  defp reply({:grab, from}, result), do: GenServer.reply(from, result)
  defp reply(_, _), do: :ok

  defp words(:no_ffmpeg), do: "ffmpeg isn't installed here, so the camera can't be read"
  defp words(:showing_video), do: "The camera is showing video; stop the video to take frames"
  defp words(:timeout), do: "The camera didn't send a frame in time. Unplug it and plug it back in"
  defp words({:ffmpeg, line}), do: "The camera said: #{line}"
  defp words(other), do: "The camera failed: #{inspect(other)}"

  # -- telling pages ---------------------------------------------------------------------------

  defp public(s) do
    %{
      camera: s.camera && describe(s.camera),
      sim: s.camera == :sim,
      live: s.live,
      video: s.video,
      busy: s.task != nil,
      settings: s.settings,
      max_exposure_ms: s.max_exposure_ms,
      has_gain: Map.has_key?(s.controls, "gain"),
      history: s.history,
      error: s.error,
      keep: s.keep,
      kept: s.kept,
      not_kept: s.not_kept,
      frames: s.frames,
      node: node()
    }
  end

  # the camera as a step on the Queues page: same numbers as a queue's, plus where a frame's time goes
  defp step_stats(s) do
    started = if s.task, do: [s.task.started], else: []
    mid = fn key -> s.parts |> Enum.map(& &1[key]) |> Enum.sort() |> Enum.at(div(length(s.parts), 2)) end

    Map.merge(Queues.Meter.read(s.meter, started, 1), %{
      name: "camera",
      label: "Take the frame",
      step: 0,
      kind: :queue,
      depth: length(s.waiting),
      depth_bytes: 0,
      max_items: 0,
      running: length(started),
      concurrency: 1,
      oldest_wait_ms: 0,
      counts: %{pushed: 0, done: s.meter.samples |> length(), failed: s.failed, dropped: 0, rejected: 0},
      paused: not s.live and s.waiting == [],
      last_error: s.error,
      parts: if(s.parts == [], do: nil, else: %{"grab" => mid.(:grab_ms), "measure here" => mid.(:analyse_ms)}),
      # every frame is numbered, so the number is a running total
      total: s.seq,
      total_bytes: nil
    })
  end

  defp publish(s) do
    Telescope.broadcast("scope_camera", {:scope_camera, public(s)})
    s
  end

  defp describe(:sim), do: "Simulated camera"
  defp describe(%{name: name, mode: %{size: {w, h}, format: f}}), do: "#{name} · #{w}×#{h} #{if f == "mjpeg", do: "JPEG", else: "raw"}"
  defp describe(%{name: name}), do: name

  defp config(key, default), do: Keyword.get(Application.get_env(:controller, :scope_camera, []), key, default)

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end
end
