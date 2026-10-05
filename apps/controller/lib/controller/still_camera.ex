defmodule Controller.StillCamera do
  @moduledoc """
  The stills camera on the telescope: a Sony a6000 in PC Remote mode, driven
  by `Camera`. Pictures on request (`shoot/0`) or one after another
  (`continuous/2`). Each is kept whole, RAW and JPEG as the camera made them,
  in `dir/0` under its night's date; nothing is ever written over.

  A small grey copy of each (960 px wide, made by ffmpeg from the JPEG) goes
  through the same measuring as the telescope camera's frames
  (`Controller.ScopeCamera.analyse/1`): background, stars, and a bright
  target's middle. That copy is what the page shows, and what
  `Controller.LockOn` steers by when it's locked on with `source: :still`.

  A picture with stars in it also says how wide they are (`star_size/2`): the
  number to focus by. That is measured on a bigger copy (3000 px wide, half
  the sensor), because at 960 px a pixel is 2.4 arcsec and a 4 arcsec star
  can't be told from a 3.

  With `solving(true)` each picture is also plate solved: a grey copy goes to
  `Controller.Plates` with the mount's encoders from the moment the shutter
  opened, so the picture says where the telescope pointed and adds to the
  mount's alignment. The answer is written beside the picture
  (`<name>.solve.json`) and shown on the page. The first solved picture also
  measures the telescope's focal length, which takes the place of the label's
  in Settings (`Controller.StillCamera.Optics`).

  **The first picture after a slew is marked, not counted.** The mount is
  still settling and there is stray light about, so that picture is often
  poor. This process follows the mount's reports and knows when it last
  slewed; a picture whose shutter opened within the settle time of that (2 s,
  `settle_ms:`) says `settling: true` in its sidecar and its record, and
  `status().good`, the count of pictures that count, doesn't move for it. The
  picture is kept all the same.

  **It carries on after a restart.** Whether it was shooting continuously and
  whether it was solving are kept in `Controller.Settings` (`"still_camera"`);
  a new process picks them up and starts shooting again as soon as the camera
  answers. A stop it made itself (three failed pictures, a full card) is kept
  too, so it doesn't start again into the same wall.

  Broadcasts `{:still_camera, status}` on `"still_camera"`.
  """
  use GenServer
  require Logger

  alias Controller.{LockOn, Plates, ScopeCamera, Settings}
  alias Controller.StillCamera.{Focus, Optics, Sidecar}

  @topic "still_camera"
  @look_ms 3_000
  @copy_w 960
  # a RAW+JPEG pair, until a picture says what this camera's really weigh
  @pair_bytes 26_000_000
  # the plate solver's copy: wide enough that a 3 arcsec star covers a pixel or two (the a6000's
  # 6000 px JPEG becomes 1500)
  @solve_w 1400
  # the copy star size is measured on: at least this wide (the a6000's 6000 px JPEG becomes 3000,
  # 0.8 arcsec a pixel at 2032 mm), and how long making and measuring it may take
  @sharp_w 3000
  @sharp_ms 15_000
  # the a6000's sensor, across: with the focal length, how much sky a picture covers
  @sensor_mm 23.5
  # how long after a slew a picture is still the mount settling
  @settle_ms 2_000
  # a slew, not tracking: faster than a tracker ever drives an axis (12x sidereal, as `Plates` has it)
  @slew_deg_s 0.05

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Where it stands: the camera, its settings, whether it's shooting, and the last picture's record."
  def status,
    do:
      :persistent_term.get({__MODULE__, :status}, %{
        camera: nil,
        seen: [],
        shooting: false,
        busy: false,
        last: nil,
        good: 0
      })

  @doc "The last picture's grey copy as a PNG (for the page), or nil."
  def png, do: :persistent_term.get({__MODULE__, :png}, nil)

  @doc """
  Take one picture now (ignored while one is being taken). Options, for this picture (those given
  to `continuous/3` stand for the rest):

    * `settle_ms:` how long after a slew a picture is still the mount settling (2000). A picture
      whose shutter opened sooner than that is marked `settling: true` and not counted;
    * `slew_deg_s:` how fast an axis must turn for it to be a slew and not tracking, in degrees a
      second (0.05, which is 12x sidereal).
  """
  def shoot(opts \\ []), do: GenServer.cast(__MODULE__, {:shoot, opts})

  @doc """
  Take pictures one after another (`interval_ms` between them, 0 for back to back), or stop.
  `opts` are `shoot/1`'s, for every picture of the run.
  """
  def continuous(on?, interval_ms \\ 0, opts \\ []),
    do: GenServer.call(__MODULE__, {:continuous, on?, interval_ms, opts})

  @doc """
  Was the mount still settling when a shutter opened? `moved` is when the mount was last seen
  slewing and `opened` when the shutter opened, both in this VM's monotonic milliseconds (which
  are negative: they are only ever compared with each other). `false` for a mount never seen
  slewing (`nil`).

      t = System.monotonic_time(:millisecond)
      StillCamera.settling?(t, t + 1_000)    #=> true
      StillCamera.settling?(t, t + 3_000)    #=> false
  """
  def settling?(moved, opened, settle_ms \\ @settle_ms)
  def settling?(moved, opened, settle_ms) when is_integer(moved) and is_integer(opened), do: opened - moved < settle_ms
  def settling?(_, _, _), do: false

  @doc """
  Is this mount snapshot a slew? A Go To in flight, or an axis turning faster than `faster_than`
  degrees a second (0.05: no tracker drives an axis that fast, and Lock On steers at about
  sidereal, 0.004). Tracking is not a slew.
  """
  def slewing?(snap, faster_than \\ @slew_deg_s)

  def slewing?(%{axes: axes}, faster_than) when is_map(axes),
    do: Enum.any?(axes, fn {_, ax} -> is_map(ax) and (ax[:goto_pending] == true or abs(ax[:deg_per_s] || 0.0) > faster_than) end)

  def slewing?(_, _), do: false

  @doc """
  Plate solve every picture from now on (or stop). A picture is solved on the box and added to the
  mount's plates (`Controller.Plates`); options for the solver: `scale:` `{low_deg, high_deg}` across
  the picture (worked out from the focal length in Settings when not given), `min_stars:` (8),
  `nsigma:` (10), `timeout:` in ms (60 000).
  """
  def solving(on?, opts \\ []), do: GenServer.call(__MODULE__, {:solving, on?, opts})

  @doc "How much sky a picture covers, across, in degrees `{low, high}`: the sensor's width through the focal length in Settings, a quarter either way."
  def field_scale do
    case Settings.get("focal_length_mm") do
      f when is_number(f) and f > 0 ->
        w = 2 * :math.atan(@sensor_mm / (2 * f)) * 180 / :math.pi()
        {w * 0.75, w * 1.25}

      _ ->
        {0.1, 5.0}
    end
  end

  @doc """
  How wide the stars in a JPEG are: the number to focus by (`Controller.StillCamera.Focus`).
  `%{arcsec:, px:, n:, w:, arcsec_per_px:, measure:}`: the median half-flux diameter of `n` stars, in
  arcseconds (nil until the focal length is in Settings) and in pixels of the copy it was measured
  on, which is `w` wide. `nil` when the picture has no stars to measure, and on any error.

  Options: `width:` the least that copy may be across (3000 px: the JPEG is decoded whole, or at a
  half, a quarter or an eighth, the smallest that is still this wide), `timeout:` in ms (15 000),
  `focal_length_mm:` (the one in Settings) and `sensor_mm:` (23.5), and `Focus.measure/3`'s own
  (`window:`, `max_stars:`, `saturation:`, `hot_px:`, `border:`).

      StillCamera.star_size(File.read!("20261004-063801-DSC01016.JPG"))
      #=> %{arcsec: 7.86, px: 9.88, n: 12, w: 3000, arcsec_per_px: 0.7951, measure: "half-flux diameter, ..."}
  """
  def star_size(jpeg, opts \\ []) do
    with n when is_integer(n) <- jpeg_width(jpeg), %{w: w, marks: %{stars: stars}} <- measure(jpeg), {size, _copy} <- sharp(jpeg, stars, w, opts), do: size, else: (_ -> nil)
  end

  @doc "Change the camera's settings: `iso:`, `shutter:` (see `Camera.Server.set/3`)."
  def set(settings), do: GenServer.call(__MODULE__, {:set, settings}, 130_000)

  def subscribe, do: Telescope.subscribe(@topic)

  @doc """
  Bytes free where pictures are kept, or nil when the system won't say. Pictures stop
  `floor_bytes/0` short of full: the box keeps its settings and its logs on the same card.
  """
  def free_bytes(dir \\ dir()) do
    File.mkdir_p(dir)

    with {out, 0} <- System.cmd("df", ["-Pk", dir], stderr_to_stdout: true),
         [_, line | _] <- String.split(out, "\n", trim: true),
         [_fs, _blocks, _used, avail | _] <- String.split(line),
         {kb, ""} <- Integer.parse(avail) do
      kb * 1024
    else
      _ -> nil
    end
  rescue
    _ -> nil
  end

  @doc "How much of the card pictures leave alone (`config :controller, still_camera_floor_mb:`, 300 MB)."
  def floor_bytes, do: Application.get_env(:controller, :still_camera_floor_mb, 300) * 1_000_000

  @doc "Where pictures are kept."
  def dir,
    do:
      Application.get_env(
        :controller,
        :still_camera_dir,
        Path.join([System.user_home!(), ".observatory", "stills"])
      )

  # -- the process -------------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    safe(fn -> Camera.subscribe() end)
    send(self(), :look)
    was = safe(fn -> Settings.get("still_camera") end) || %{}

    {:ok,
     announce(%{
       camera: nil,
       seen: [],
       continuous: was["continuous"] == true,
       interval_ms: (is_integer(was["interval_ms"]) && was["interval_ms"]) || 0,
       # a :shoot_next is on its way: so the look loop can start one when none is (after a restart, a lost message)
       armed: false,
       task: nil,
       seq: 0,
       last: nil,
       failures: 0,
       why: nil,
       free: free_bytes(),
       looks: 0,
       solving: was["solving"] == true,
       solve_opts: [],
       solve: nil,
       watching: MapSet.new(),
       # the run's options for each picture (`shoot/1`'s)
       shot_opts: [],
       # the mounts whose reports are followed, and when each was last seen slewing (monotonic ms)
       mounts: MapSet.new(),
       moved: %{},
       # pictures that count: taken with the mount settled
       good: 0
     })}
  end

  @impl true
  def handle_call({:continuous, on?, interval, opts}, _from, s) do
    s = persist(%{s | continuous: on?, interval_ms: interval, shot_opts: opts, failures: 0, why: nil})
    s = if on? and s.task == nil and not s.armed, do: arm(s, 0), else: s
    {:reply, :ok, announce(s)}
  end

  def handle_call({:solving, on?, opts}, _from, s), do: {:reply, :ok, announce(persist(%{s | solving: on?, solve_opts: opts}))}

  def handle_call({:set, settings}, _from, %{camera: %{id: id}} = s) do
    reply = safe(fn -> Camera.set(id, settings) end) || {:error, :camera_busy}
    {:reply, reply, s |> look() |> announce()}
  end

  def handle_call({:set, _}, _from, s), do: {:reply, {:error, :no_camera}, s}

  @impl true
  def handle_cast({:shoot, opts}, s), do: {:noreply, start_shot(s, Keyword.merge(s.shot_opts, opts))}

  @impl true
  def handle_info(:look, s) do
    Process.send_after(self(), :look, @look_ms)
    # the card's room, every half minute: other things write to it too
    s = if rem(s.looks, 10) == 0 and s.task == nil, do: %{s | free: free_bytes()}, else: s
    s = look(%{s | looks: s.looks + 1})
    # shooting continuously with nothing in flight and nothing on its way: start one (the camera
    # just came back, or the box did)
    s = if s.continuous and s.task == nil and not s.armed and match?(%{state: :ready}, s.camera), do: arm(s, 0), else: s
    {:noreply, announce(s)}
  end

  def handle_info({:camera, _st}, s), do: {:noreply, s |> look() |> announce()}

  # A mount's report (four a second, and on every change): all that matters here is when it was
  # last slewing. Stamped as it is read, so reports read late (this process was busy turning a
  # dial) say "later" and a picture is marked that needn't have been: never the other way round.
  def handle_info({:mount, %{id: id} = snap}, s) do
    if slewing?(snap, s.shot_opts[:slew_deg_s] || @slew_deg_s),
      do: {:noreply, %{s | moved: Map.put(s.moved, id, System.monotonic_time(:millisecond))}},
      else: {:noreply, s}
  end

  # a plate moved on (solving, solved, failed): is it the one this picture is waiting for?
  def handle_info({:plates, mount, view}, %{solve: %{mount: mount, n: n} = solve} = s) when is_integer(n) do
    {:noreply, announce(%{s | solve: plate_state(solve, view)})}
  end
  def handle_info(:shoot_next, s) do
    s = %{s | armed: false}
    {:noreply, if(s.continuous, do: start_shot(s), else: s)}
  end

  def handle_info({ref, result}, %{task: %Task{ref: ref}} = s) do
    Process.demonitor(ref, [:flush])
    {:noreply, finished(%{s | task: nil}, result)}
  end

  def handle_info({:DOWN, ref, :process, _, reason}, %{task: %Task{ref: ref}} = s) do
    {:noreply, finished(%{s | task: nil}, {:error, {:crashed, reason}})}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp look(s) do
    cams = safe(fn -> Camera.list() end) || []

    %{
      s
      | camera: Enum.find(cams, &(&1[:state] == :ready)) || List.first(cams),
        seen: safe(fn -> Camera.seen() end) || []
    }
    |> follow_mounts()
  end

  # Follow the mounts a picture may be taken through, to know when one last slewed: this box's
  # own and the one Lock On holds (both free to ask), and any a picture did go through.
  defp follow_mounts(s, more \\ []) do
    here = for %{id: id} <- safe(fn -> Mount.local_list() end) || [], do: id
    lock = safe(fn -> LockOn.status()[:mount] end)

    Enum.reduce(more ++ [lock | here], s, fn id, s ->
      if is_binary(id) and not MapSet.member?(s.mounts, id) and safe(fn -> Mount.subscribe(id) end) == :ok, do: %{s | mounts: MapSet.put(s.mounts, id)}, else: s
    end)
  end

  defp start_shot(s, opts \\ nil)

  defp start_shot(%{task: nil, camera: %{id: id, state: :ready}} = s, opts) do
    if is_integer(s.free) and s.free < floor_bytes() + pair_bytes(s) do
      # no room: say so and stop, rather than fill the card the box itself lives on
      announce(persist(%{s | continuous: false, why: "the SD card is nearly full (#{div(s.free, 1_000_000)} MB free): copy the pictures off the box, then carry on"}))
    else
      seq = s.seq + 1
      dir = dir()
      solve = if s.solving, do: s.solve_opts
      # what this process knows that the picture's own task doesn't: when each mount last slewed
      ctx = %{moved: s.moved, opts: opts || s.shot_opts}
      task = Task.Supervisor.async_nolink(Controller.StillCamera.Tasks, fn -> take(id, seq, dir, solve, ctx) end)
      announce(%{s | task: task, seq: seq})
    end
  end

  defp start_shot(s, _opts), do: s

  defp pair_bytes(%{last: %{bytes: b}}) when is_integer(b) and b > 0, do: b
  defp pair_bytes(_), do: @pair_bytes

  # One picture: the camera's files kept whole, what was known when it was taken written beside
  # them (`Sidecar`), then the grey copy measured. The mount is watched while the shutter is open.
  defp take(id, seq, dir, solve, ctx) do
    started = System.monotonic_time(:millisecond)
    mount_id = mount_id()
    watch = Sidecar.watch(mount_id)
    result = Camera.capture(id)
    samples = Sidecar.stop(watch)

    with {:ok, files} <- result do
      saved_at = DateTime.utc_now()
      pressed = hd(files)[:pressed_at] || saved_at
      night = Path.join(dir, Date.to_iso8601(DateTime.to_date(pressed)))
      File.mkdir_p!(night)
      stamp = fresh(night, Calendar.strftime(pressed, "%Y%m%d-%H%M%S"), files)

      kept =
        for f <- files do
          name = "#{stamp}-#{f.name}"
          File.write!(Path.join(night, name), f.bytes, [:exclusive])
          %{name: name, camera_name: f.name, format: f.format, bytes: byte_size(f.bytes), sha256: Base.encode16(:crypto.hash(:sha256, f.bytes), case: :lower)}
        end

      jpeg = Enum.find(files, &(&1.format == :jpeg))
      frame = jpeg && measure(jpeg.bytes)
      # how wide its stars are, and the bigger copy that was measured on (the solver's starts from it)
      {star_size, sharp} = if frame, do: sharp(jpeg.bytes, frame.marks.stars, frame.w, []), else: {nil, nil}

      measured =
        frame &&
          %{
            copy: "#{@copy_w} px wide, grey, the sensor's way up",
            w: frame.w,
            h: frame.h,
            background: frame.stats.background,
            max: frame.stats.max,
            stars: frame.focus.stars,
            bright: frame[:bright],
            star_size: star_size
          }

      base = "#{stamp}-#{Path.rootname(hd(files).name)}"
      camera = safe(fn -> Camera.status(id) end)
      # How the camera was set when the shutter was pressed, as its driver read it then. The status
      # asked now is a later reading: an ISO turned while this picture came down and was measured is
      # already in it (the night a frame taken at ISO 3200 was written down as 800).
      settings = hd(files)[:settings]
      exposure_s = Sidecar.seconds((settings || get_in(camera || %{}, [:settings]) || %{})[:shutter]) || 0.0
      settle = mount_id && settle(ctx.moved[mount_id], samples, pressed, hd(files)[:pressed_mono] || started, exposure_s, ctx.opts)
      plate = if solve && jpeg, do: to_plates(mount_id, jpeg.bytes, samples, pressed, exposure_s, solve, sharp)

      # a sidecar that can't be written never costs the picture
      sidecar =
        try do
          %{
            seq: seq,
            saved_at: saved_at,
            pressed_at: pressed,
            ready_at: hd(files)[:ready_at],
            files: kept,
            camera: camera,
            settings: settings,
            mount_id: mount_id,
            samples: samples,
            settle: settle,
            lock: LockOn.status(),
            calibration: mount_id && safe(fn -> LockOn.calibration(mount_id) end),
            measured: measured,
            plate: plate
          }
          |> Sidecar.build()
          |> then(&Sidecar.write(night, base, &1))
        rescue
          e ->
            Logger.warning("still camera: the sidecar wasn't written: #{Exception.message(e)}")
            nil
        end

      record = %{
        seq: seq,
        at: pressed,
        plate: plate,
        base: Path.join(night, base),
        ok: true,
        took_ms: System.monotonic_time(:millisecond) - started,
        files: Enum.map(kept, &Path.join(night, &1.name)),
        names: Enum.map(files, & &1.name),
        bytes: kept |> Enum.map(& &1.bytes) |> Enum.sum(),
        sidecar: sidecar,
        mount: mount_id,
        settling: settle && settle.settling,
        since_slew_s: settle && settle.since_slew_s,
        # the camera's JPEG, across: the sensor's whole width in this many pixels
        full_w: jpeg && jpeg_width(jpeg.bytes)
      }

      record = if frame, do: Map.merge(record, Map.merge(Map.drop(measured, [:copy]), %{marks: frame.marks, png: frame.png})), else: record
      {:ok, record}
    end
  end

  # Was the mount still settling when this picture's shutter opened? It last slewed when this
  # process's reports said so (`moved`, handed over as the picture started), or in a sample taken
  # just before the press. The samples from while the shutter was open say whether it slewed then:
  # a picture the mount moved under is no better than one it was settling under. `opened` is the
  # press by the monotonic clock, `pressed` the same moment by the wall clock the samples carry
  # (used only for how far a sample is from the press, a second or so at most).
  defp settle(moved, samples, pressed, opened, exposure_s, opts) do
    settle_ms = opts[:settle_ms] || @settle_ms
    faster = opts[:slew_deg_s] || @slew_deg_s
    # each sample the mount was slewing in, as ms after the press (before it: negative); one sample
    # past the exposure's end still belongs to it, since they are 250 ms apart
    slews = for {t, snap} <- samples, slewing?(snap, faster), d = DateTime.diff(t, pressed, :millisecond), d <= exposure_s * 1000 + 250, do: d
    during? = Enum.any?(slews, &(&1 >= 0))
    moved = Enum.max(for(d <- slews, d < 0, do: opened + d) ++ if(is_integer(moved), do: [moved], else: []), fn -> nil end)
    since = if during?, do: 0, else: moved && max(opened - moved, 0)

    %{
      settling: during? or settling?(moved, opened, settle_ms),
      since_slew_s: since && Float.round(since / 1000, 2),
      settle_s: settle_ms / 1000
    }
  end

  # Nothing is ever written over: when a file of this name is already there (two pictures in one
  # second from a camera whose numbering started again), the stamp gets a letter.
  defp fresh(night, stamp, files) do
    Enum.find([stamp | for(c <- ?b..?z, do: stamp <> <<c>>)], stamp <> "z", fn st ->
      not Enum.any?(files, &File.exists?(Path.join(night, "#{st}-#{&1.name}")))
    end)
  end

  # The picture to the plate queue, with the mount as it was when the shutter opened (the sample
  # nearest the middle of the exposure). `%{mount, n}` when queued, `%{error: why}` when it couldn't be.
  defp to_plates(nil,_jpeg, _samples, _pressed, _exposure_s, _opts, _sharp), do: %{error: "no mount to solve for"}

  defp to_plates(mount_id, jpeg, samples, pressed, exposure_s, opts, sharp) do
    mid = DateTime.add(pressed, round(exposure_s * 500), :millisecond)

    with [_ | _] = snaps <- Enum.filter(samples, fn {_, snap} -> is_map(snap) and is_map(snap[:axes]) end),
         {_, snap} = Enum.min_by(snaps, fn {t, _} -> abs(DateTime.diff(t, mid, :millisecond)) end),
         cap when is_map(cap) <- Plates.capture(Map.put_new(snap, :id, mount_id), now: mid, report: safe(fn -> Plates.view(mount_id)[:report] end)),
         pgm when is_binary(pgm) <- solver_copy(jpeg, sharp) do
      solver = [scale: opts[:scale] || field_scale(), min_stars: opts[:min_stars] || 8, nsigma: opts[:nsigma] || 10, timeout: opts[:timeout] || 150_000]

      case safe(fn -> Plates.add(mount_id, pgm, cap, solver) end) do
        {:ok, n} -> %{mount: mount_id, n: n}
        {:error, why} -> %{error: "the plate queue refused it: #{inspect(why)}"}
        _ -> %{error: "the plate queue isn't running"}
      end
    else
      [] -> %{error: "the mount wasn't answering when the picture was taken"}
      _ -> %{error: "no copy could be made for the solver (ffmpeg)"}
    end
  end

  # where a waiting picture's plate stands, from the plates' own view
  defp plate_state(solve, view) do
    case Enum.find(view[:plates] || [], &(&1.n == solve.n)) do
      nil ->
        %{solve | state: :failed, reason: "forgotten"}

      p ->
        solve = %{solve | state: p.state, reason: p[:reason], solution: p[:solution], residual_arcmin: p[:residual_arcmin]}
        if p.state in [:solved, :failed] and not solve.written, do: solve |> learn() |> write_solve(), else: solve
    end
  end

  # A solved picture measures the telescope. The field's width over the picture's pixels is the sky
  # a pixel covers, the sensor's width over the same pixels is the pixel, and the two give the focal
  # length (`Optics`): 2,084 mm from the 8SE's plates, where the label says 2,032. The first one is
  # kept with the optics in Settings; every solve's own goes into its answer.
  defp learn(%{state: :solved, solution: %{width_deg: w}, full_w: px} = solve) when is_number(w) and w > 0 and is_integer(px) and px > 0 do
    {scale, pixel} = {w * 3600 / px, @sensor_mm * 1000 / px}
    safe(fn -> Optics.learn(scale, pixel, plate: Path.basename(solve.base)) end)
    %{solve | focal_length_mm: Float.round(Optics.focal_length_mm(scale, pixel), 1)}
  end

  defp learn(solve), do: solve

  # the answer beside the picture, once
  defp write_solve(solve) do
    record = %{
      schema: "observatory.still.solve/1",
      picture: Path.basename(solve.base),
      mount: solve.mount,
      plate: solve.n,
      state: solve.state,
      reason: solve.reason,
      solution: solve.solution,
      focal_length_mm: solve.focal_length_mm,
      written: DateTime.utc_now() |> DateTime.to_iso8601()
    }

    safe(fn -> File.write!(solve.base <> ".solve.json", Jason.encode_to_iodata!(record, pretty: true)) end)
    %{solve | written: true}
  end

  # the mount these pictures are taken through: the one Lock On holds, else this box's own (a real
  # one before a simulated one), else any the cluster has
  defp mount_id do
    case LockOn.status() do
      %{state: state, mount: id} when state != :off and is_binary(id) ->
        id

      _ ->
        here = safe(fn -> Mount.local_list() end) || []
        mounts = if here == [], do: safe(fn -> Mount.list() end) || [], else: here

        case Mount.default(mounts) do
          %{id: id} -> id
          id when is_binary(id) -> id
          _ -> nil
        end
    end
  end

  # The JPEG, small and grey, through the telescope camera's measuring. Always the sensor's own way
  # up (-noautorotate): the camera's tilt sensor flips its rotation flag as the scope slews, and a
  # picture that turns 90° under Lock On ruins its calibration. A big JPEG is decoded at a quarter or
  # an eighth of its size (-lowres), still wider than the copy: 0.9 s on a Pi instead of 5.8.
  defp measure(jpeg) do
    with pgm when is_binary(pgm) <- grey(jpeg, lowres(jpeg_width(jpeg)), "scale=#{@copy_w}:-2,format=gray"), do: ScopeCamera.analyse(pgm)
  rescue
    _ -> nil
  end

  # How wide the stars are (`Focus`), on a copy at half the sensor's size or more: `{star size, the
  # copy}`, either of them nil. `stars` are the measuring copy's marks, and `from_w` that copy's
  # width. In a task of its own, with a deadline: the picture's files are on the card by now, and
  # nothing that goes wrong here (no ffmpeg, an ffmpeg that hangs, a picture of nothing) can cost
  # them or hold them up for long. The copy (`%{pgm:, low:}`) is handed on, so the solver's is made
  # from it and the JPEG isn't decoded at that size twice. No stars, no copy: nothing is decoded.
  defp sharp(_jpeg, [], _from_w, _opts), do: {nil, nil}

  defp sharp(jpeg, stars, from_w, opts) do
    # the JPEG's file for ffmpeg is named here, so a task cut off at the deadline leaves none behind
    tmp = Path.join(System.tmp_dir!(), "still-sharp-#{System.unique_integer([:positive])}.jpg")

    task =
      Task.Supervisor.async_nolink(Controller.StillCamera.Tasks, fn ->
        safe(fn ->
          low = lowres(jpeg_width(jpeg), opts[:width] || @sharp_w)

          with pgm when is_binary(pgm) <- grey(jpeg, low, "format=gray", tmp), {:ok, img} <- ScopeCamera.Image.from_pgm(pgm) do
            size =
              with %{hfd_px: px, n: n} <- Focus.measure(img, stars, Keyword.put(opts, :scale, img.w / from_w)) do
                scale = Focus.arcsec_per_px(opts[:focal_length_mm] || Settings.get("focal_length_mm"), opts[:sensor_mm] || @sensor_mm, img.w)

                %{
                  measure: "half-flux diameter, the median of its stars",
                  arcsec: scale && Float.round(px * scale, 2),
                  px: Float.round(px, 2),
                  n: n,
                  w: img.w,
                  arcsec_per_px: scale && Float.round(scale, 4)
                }
              end

            {size, %{pgm: pgm, low: low}}
          else
            _ -> {nil, nil}
          end
        end)
      end)

    case Task.yield(task, opts[:timeout] || @sharp_ms) || Task.shutdown(task, :brutal_kill) do
      {:ok, {_size, _copy} = found} ->
        found

      _ ->
        File.rm(tmp)
        {nil, nil}
    end
  rescue
    _ -> {nil, nil}
  catch
    _, _ -> {nil, nil}
  end

  # The solver's copy. A camera's JPEG has hot pixels (26 in a 1 s dark frame from the a6000), and
  # to a star finder each is a star: a starless picture then has enough "stars" to start the solver,
  # which grinds to its deadline. A hot pixel is one pixel wide; a star through a telescope is
  # several. So the JPEG is decoded at twice the width the solver needs, single-pixel specks are
  # taken out there (a 3x3 median), and it is halved by averaging. On the Pi: 2 s. When star size
  # has already decoded the picture at that size (`sharp`), the copy starts from that one (the same
  # bytes come out) and the JPEG isn't decoded again.
  defp solver_copy(jpeg, sharp) do
    w = jpeg_width(jpeg)
    {low, filter} = if is_integer(w) and w >= 2 * @solve_w, do: {lowres(w, 2 * @solve_w), "median=radius=1,scale=iw/2:ih/2:flags=area"}, else: {0, "median=radius=1"}
    from_sharp = with %{pgm: pgm, low: ^low} <- sharp, <<"P5", _::binary>> = copy <- safe(fn -> regrey(pgm, filter) end), do: copy, else: (_ -> nil)
    from_sharp || grey(jpeg, low, "format=gray," <> filter)
  end

  # a grey PGM of the JPEG, the sensor's way up, decoded at 1/2^low of its size, through `filter`
  # (`tmp`: where the JPEG is put for ffmpeg, for a caller that may have to clear it away itself)
  defp grey(jpeg, low, filter, tmp \\ nil) do
    with exe when is_binary(exe) <- System.find_executable("ffmpeg") || existing("/usr/bin/ffmpeg") do
      tmp = tmp || Path.join(System.tmp_dir!(), "still-#{System.unique_integer([:positive])}.jpg")
      args = ~w(-loglevel error -noautorotate -lowres #{low} -i #{tmp} -vf #{filter} -frames:v 1 -f image2pipe -vcodec pgm -)

      try do
        File.write!(tmp, jpeg)
        with {pgm, 0} <- System.cmd(exe, args), do: pgm, else: (_ -> nil)
      after
        File.rm(tmp)
      end
    end
  end

  # a grey PGM made from one already decoded, through `filter`: no JPEG is decoded
  defp regrey(pgm, filter) do
    with exe when is_binary(exe) <- System.find_executable("ffmpeg") || existing("/usr/bin/ffmpeg") do
      tmp = Path.join(System.tmp_dir!(), "still-#{System.unique_integer([:positive])}.pgm")
      args = ~w(-loglevel error -i #{tmp} -vf #{filter} -frames:v 1 -f image2pipe -vcodec pgm -)

      try do
        File.write!(tmp, pgm)
        with {out, 0} <- System.cmd(exe, args), do: out, else: (_ -> nil)
      after
        File.rm(tmp)
      end
    end
  end

  @doc false
  # how far the decoder can shrink it and stay at least as wide as the copy: 6000 px is 2 (1500 px)
  def lowres(w, at_least \\ @copy_w)
  def lowres(nil, _), do: 0
  def lowres(w, at_least), do: Enum.find([3, 2, 1], 0, &(div(w, Bitwise.bsl(1, &1)) >= at_least))

  @doc false
  # the picture's width from its frame header, past the EXIF block (whose thumbnail has its own)
  def jpeg_width(<<0xFF, 0xD8, rest::binary>>), do: segment_width(rest)
  def jpeg_width(_), do: nil

  defp segment_width(<<0xFF, m, _len::16, _bits, _h::16, w::16, _::binary>>) when m in 0xC0..0xCF and m not in [0xC4, 0xC8, 0xCC], do: w
  defp segment_width(<<0xFF, 0xFF, rest::binary>>), do: segment_width(<<0xFF, rest::binary>>)
  defp segment_width(<<0xFF, _m, len::16, rest::binary>>) when len >= 2 and byte_size(rest) >= len - 2, do: segment_width(binary_part(rest, len - 2, byte_size(rest) - len + 2))
  defp segment_width(_), do: nil

  defp existing(path), do: if(File.exists?(path), do: path)

  defp finished(s, {:ok, record}) do
    if png = record[:png], do: :persistent_term.put({__MODULE__, :png}, png)
    # the star size of the picture before rides along: a page says which way a focus turn went
    record = record |> Map.delete(:png) |> Map.put(:star_size_was, s.last && s.last[:star_size])
    LockOn.frame(Map.put(record, :source, :still))
    good = if counts?(record), do: s.good + 1, else: s.good
    s = %{s | last: record, good: good, failures: 0, why: nil, free: free_bytes()} |> follow(record) |> follow_mounts([record[:mount]])
    announce(if s.continuous, do: arm(s, s.interval_ms), else: s)
  end

  defp finished(s, {:error, reason}) do
    Logger.warning("still camera: #{inspect(reason)}")
    failures = s.failures + 1

    s =
      cond do
        s.continuous and failures >= 3 ->
          persist(%{s | continuous: false, why: "stopped after three failed pictures in a row: #{words(reason)}"})

        s.continuous ->
          arm(%{s | why: "a picture failed: #{words(reason)}; trying again"}, 2_000)

        true ->
          %{s | why: "the picture failed: #{words(reason)}"}
      end

    announce(%{s | failures: failures})
  end

  # a picture that counts: every one that isn't marked (the mount settling)
  defp counts?(record), do: record[:settling] != true

  # this picture's plate: follow it on its mount's plates until it is solved or failed
  defp follow(s, %{plate: %{mount: mount, n: n}, seq: seq, base: base} = record) do
    s = if MapSet.member?(s.watching, mount), do: s, else: (Plates.subscribe(mount); %{s | watching: MapSet.put(s.watching, mount)})
    solve = %{seq: seq, mount: mount, n: n, base: base, state: :queued, reason: nil, solution: nil, residual_arcmin: nil, written: false, full_w: record[:full_w], focal_length_mm: nil}
    # it may have been solved before the picture's files were all saved
    %{s | solve: plate_state(solve, safe(fn -> Plates.view(mount) end) || %{plates: [%{n: n, state: :queued}]})}
  end

  defp follow(s, %{plate: %{error: why}, seq: seq}), do: %{s | solve: %{seq: seq, state: :failed, reason: why, solution: nil, n: nil, mount: nil}}
  defp follow(s, _), do: s

  # the next picture, now or in `delay` ms
  defp arm(s, 0), do: (send(self(), :shoot_next); %{s | armed: true})
  defp arm(s, delay), do: (Process.send_after(self(), :shoot_next, delay); %{s | armed: true})

  # what a restart should come back to
  defp persist(s) do
    now = %{"continuous" => s.continuous, "interval_ms" => s.interval_ms, "solving" => s.solving}
    if safe(fn -> Settings.get("still_camera") end) != now, do: safe(fn -> Settings.put("still_camera", now) end)
    s
  end

  defp words(:timeout), do: "the camera stopped answering"
  defp words(:no_picture), do: "the camera never said the picture was ready"
  defp words({:refused, code}), do: "the camera refused (#{code})"
  defp words(other), do: inspect(other)

  defp announce(s) do
    st = %{
      camera: s.camera,
      seen: s.seen,
      shooting: s.continuous,
      interval_ms: s.interval_ms,
      busy: s.task != nil,
      last: s.last,
      good: s.good,
      why: s.why,
      solving: s.solving,
      solve: s.solve && Map.take(s.solve, [:seq, :mount, :n, :state, :reason, :solution, :residual_arcmin]),
      free_mb: if(is_integer(s.free), do: div(s.free, 1_000_000)),
      room_for: if(is_integer(s.free), do: max(div(s.free - floor_bytes(), pair_bytes(s)), 0))
    }

    if :persistent_term.get({__MODULE__, :status}, nil) != st do
      :persistent_term.put({__MODULE__, :status}, st)
      safe(fn -> Telescope.broadcast(@topic, {:still_camera, st}) end)
    end

    s
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end
end

defmodule Controller.StillCamera.Supervisor do
  @moduledoc """
  The stills camera's own branch: its process and the tasks that take each
  picture (a picture that crashes is one failed picture). Restarted a few
  times, then left down, so a fault here can't reach the mount.
  """
  use Supervisor

  def start_link(_), do: Supervisor.start_link(__MODULE__, nil, name: __MODULE__)

  @impl true
  def init(_) do
    Supervisor.init(
      [{Task.Supervisor, name: Controller.StillCamera.Tasks}, Controller.StillCamera],
      strategy: :rest_for_one,
      max_restarts: 5,
      max_seconds: 60
    )
  end
end
