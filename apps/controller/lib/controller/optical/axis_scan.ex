defmodule Controller.Optical.AxisScan do
  @moduledoc """
  Find the mount's axes in the camera picture by moving them.

  The procedure, per axis: take a still, turn the axis a small known amount,
  take another, turn back. Block-match the two stills for what moved and fit
  a rotation centre to the flow. The result is drawn over the "before"
  frame: arrows where things moved, a mark where the axis appears to pivot,
  and honest words about how well a pivot explains the motion.

  Runs on demand only, one at a time, as a supervised task; progress and the
  result are broadcast on `"optical"` and kept in Settings under
  `optical_axes` per mount. Moves are ±3° — nothing a cable minds.
  """
  use GenServer
  require Logger

  alias Controller.Optical.{Flow, Frame, Pivot}
  alias Controller.Settings

  # 3° moves the tube end ~15 px at 1920 wide: enough to measure, nothing a cable minds
  @delta_deg 3.0
  # grey frames at a third of the size: 640×360 from a 1080p still
  @factor 3
  @settle_ms 1_500
  @topic "optical"

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Start a scan of both axes on mount `id`. `{:error, :busy}` if one is running."
  def run(id, opts \\ []), do: GenServer.call(__MODULE__, {:run, id, opts})

  @doc """
  The sweep: five positions per axis (−6°, −3°, 0°, +3°, +6°), a still at rest
  at each, spots tracked through the sequence, the axis fitted in 3-D with
  its margins. Two to three minutes. `{:error, :busy}` if anything is running.
  """
  def sweep(id, opts \\ []), do: GenServer.call(__MODULE__, {:run, id, Keyword.put(opts, :mode, :sweep)})

  @doc "Sweep ranges offered: half-angle in degrees. ±6° is gentle; ±20° bows the arcs enough to see depth."
  def ranges, do: [6.0, 20.0]

  def status, do: GenServer.call(__MODULE__, :status)
  def subscribe, do: Telescope.subscribe(@topic)

  @doc "The last result for a mount, or nil."
  def result(id), do: Settings.get("optical_axes", %{}) |> Map.get(id)

  def clear(id), do: Settings.put("optical_axes", Map.delete(Settings.get("optical_axes", %{}), id))

  @impl true
  def init(_) do
    Process.flag(:trap_exit, true)
    {:ok, %{task: nil, id: nil, step: nil, error: nil}}
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, Map.take(s, [:id, :step, :error]) |> Map.put(:running, s.task != nil), s}

  def handle_call({:run, _id, _}, _from, %{task: t} = s) when t != nil, do: {:reply, {:error, :busy}, s}

  def handle_call({:run, id, opts}, _from, s) do
    case Enum.find(Mount.list(), &(&1.id == id)) do
      nil ->
        {:reply, {:error, :no_mount}, s}

      ref ->
        parent = self()
        task = Task.async(fn -> if(opts[:mode] == :sweep, do: sweep_scan(parent, ref, opts), else: scan(parent, ref, id, opts)) end)
        {:reply, :ok, announce(%{s | task: task, id: id, step: :starting, error: nil})}
    end
  end

  @impl true
  def handle_info({:step, step}, s), do: {:noreply, announce(%{s | step: step})}

  def handle_info({ref, result}, %{task: %{ref: ref}} = s) do
    Process.demonitor(ref, [:flush])

    s =
      case result do
        {:ok, %{sweep: sweep}} ->
          Telescope.Events.emit(:optical, :sweep_done, %{id: s.id, ra: sweep_words(sweep["ra"]), dec: sweep_words(sweep["dec"]), between: sweep["between_deg"]})
          all = Settings.get("optical_axes", %{})
          prev = get_in(all, [s.id, "sweep", "history"]) || []
          history = if(sweep["pair"], do: [sweep["pair"]["polar"]["dir"] | prev], else: prev) |> Enum.take(5)
          sweep = Map.merge(sweep, %{"history" => history, "history_n" => length(history), "history_spread_deg" => spread_deg(history)})
          entry = Map.get(all, s.id, %{}) |> Map.put("sweep", sweep)
          Settings.put("optical_axes", Map.put(all, s.id, entry))
          %{s | task: nil, step: :done}

        {:ok, res} ->
          Telescope.Events.emit(:optical, :axes_found, %{id: s.id, ra: summary(res.ra), dec: summary(res.dec)})
          all = Settings.get("optical_axes", %{})
          entry = Map.get(all, s.id, %{}) |> Map.take(["sweep"]) |> Map.merge(stringify(res))
          Settings.put("optical_axes", Map.put(all, s.id, entry))
          %{s | task: nil, step: :done}

        {:error, why} ->
          Logger.warning("optical: scan failed: #{inspect(why)}")
          %{s | task: nil, step: :failed, error: to_string(why)}
      end

    {:noreply, announce(s)}
  end

  def handle_info({:DOWN, _ref, :process, _pid, reason}, s) do
    {:noreply, announce(%{s | task: nil, step: :failed, error: "scan crashed: #{inspect(reason)}"})}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- the procedure, in the task ------------------------------------------------------

  defp scan(parent, ref, _id, opts) do
    delta = opts[:delta_deg] || @delta_deg
    Telescope.Events.tag("axis scan")

    with :ok <- camera_ready(),
         {:ok, before, before_name, _} <- capture(parent, :capture_before),
         {:ok, ra} <- axis(parent, ref, :ra, delta, before),
         {:ok, dec} <- axis(parent, ref, :dec, delta, before) do
      {:ok, %{"at" => DateTime.to_iso8601(DateTime.utc_now()), "frame" => before_name, "delta_deg" => delta, "scale" => before.scale, "w" => before.w, "h" => before.h, ra: ra, dec: dec}}
    end
  end

  # -- the sweep ------------------------------------------------------------------------

  defp sweep_scan(parent, ref, opts) do
    Telescope.Events.tag("axis sweep")
    hfov = Settings.get("camera_hfov_deg", 70) / 1
    half = (opts[:range] || 6.0) / 1
    angles = [-half, -half / 2, 0.0, half / 2, half]

    # the encoders at the sweep's centre position: the live overlay rotates from here
    ref_enc =
      case Mount.snapshot(ref) do
        %{axes: %{ra: %{degrees: r}, dec: %{degrees: d}}} -> %{"ra" => r / 1, "dec" => d / 1}
        _ -> %{"ra" => 0.0, "dec" => 0.0}
      end

    with :ok <- camera_ready(),
         {:ok, ra} <- sweep_axis(parent, ref, :ra, hfov, angles),
         {:ok, dec} <- sweep_axis(parent, ref, :dec, hfov, angles) do
      between =
        case {ra["fit"], dec["fit"]} do
          {%{} = a, %{} = b} -> Float.round(Controller.Optical.Axis3D.angle_between(%{dir: List.to_tuple(a["dir"])}, %{dir: List.to_tuple(b["dir"])}), 1)
          _ -> nil
        end

      send(parent, {:step, :pair_fit})
      pair = pair_fit(ra, dec, angles, hfov)

      {:ok, %{sweep: %{"at" => DateTime.to_iso8601(DateTime.utc_now()), "hfov_deg" => hfov, "angles" => angles, "range_deg" => half, "between_deg" => between, "ref" => ref_enc, "ra" => ra, "dec" => dec, "pair" => pair}}}
    end
  end

  # to −half, then +half/2 four times with a still at rest at each, then back to where we started
  defp sweep_axis(parent, ref, axis, hfov, angles) do
    half = -hd(angles)
    steps = [-half, half / 2, half / 2, half / 2, half / 2]

    result =
      Enum.reduce_while(Enum.with_index(steps), {:ok, []}, fn {step, i}, {:ok, frames} ->
        send(parent, {:step, {:sweep, axis, i + 1, length(steps)}})

        with :ok <- Mount.goto_relative(ref, axis, step),
             :ok <- settle(ref, axis),
             after_at = DateTime.add(DateTime.utc_now(), if(streaming?(), do: 5, else: 0), :second),
             {:ok, frame, name, _} <- capture(parent, {:sweep, axis, i + 1, length(steps)}, after_at) do
          {:cont, {:ok, [{frame, name} | frames]}}
        else
          {:error, :limit} -> {:halt, {:error, "#{axis}: soft limit during the sweep"}}
          {:error, e} -> {:halt, {:error, "#{axis}: #{inspect(e)}"}}
        end
      end)

    # back to where we started whatever happened
    _ = Mount.goto_relative(ref, axis, -half)
    _ = settle(ref, axis)

    with {:ok, frames_rev} <- result,
         frames = Enum.reverse(frames_rev),
         :ok <- frames_alive(frames) do
      send(parent, {:step, {:analyse, axis}})
      list = Enum.map(frames, &elem(&1, 0))
      names = Enum.map(frames, &elem(&1, 1))
      tracks = Controller.Optical.Track.trajectories(list)
      %{w: w, h: h, scale: scale} = hd(list)
      cam = Controller.Optical.Axis3D.camera(w, h, hfov)

      fit =
        case Controller.Optical.Axis3D.fit(tracks, angles, cam) do
          {:ok, f} -> fit_json(f, cam)
          {:error, _} -> nil
        end

      {:ok,
       %{
         "frames" => names,
         "w" => w,
         "h" => h,
         "scale" => scale,
         "tracks" => Enum.map(tracks, fn %{points: pts} -> Enum.map(pts, fn {x, y} -> [x, y] end) end),
         "fit" => fit
       }}
    end
  end

  # every still the same bytes means the camera has frozen; say so instead of fitting noise
  defp frames_alive(frames) do
    hashes = Enum.map(frames, fn {f, _} -> :erlang.phash2(f.pixels) end)
    if length(Enum.uniq(hashes)) <= 1, do: {:error, "the camera is frozen — every picture is identical; stop and restart the video, or replug the camera"}, else: :ok
  end

  # Both axes at once, perpendicular by construction, started from the single
  # fits; plus what the camera says each commanded step actually turned.
  defp pair_fit(%{"fit" => %{} = rf, "tracks" => rt, "w" => w, "h" => h}, %{"fit" => %{} = df, "tracks" => dt}, angles, hfov) do
    alias Controller.Optical.Axis3D
    cam = Axis3D.camera(w, h, hfov)
    to_tracks = fn ts -> Enum.map(ts, fn pts -> %{points: Enum.map(pts, fn [x, y] -> {x, y} end)} end) end
    ra_t = to_tracks.(rt)
    dec_t = to_tracks.(dt)
    single = fn f -> %{dir: List.to_tuple(f["dir"]), point: List.to_tuple(f["point"]), sense: f["sense"], tilt_ambiguous: f["tilt_ambiguous"]} end

    case Axis3D.fit_pair(ra_t, dec_t, angles, cam, polar: single.(rf), dec: single.(df)) do
      {:ok, r} ->
        steps = fn fit, tracks -> Axis3D.measured_angles(fit, tracks, angles, cam) |> Enum.map(&Map.new(&1, fn {k, v} -> {Atom.to_string(k), v} end)) end
        ra_steps = steps.(r.polar, ra_t)
        dec_steps = steps.(r.dec, dec_t)

        %{
          "polar" => fit_json(r.polar, cam),
          "dec" => fit_json(r.dec, cam),
          "rms_px" => Float.round(r.rms_px, 2),
          "steps" => %{"ra" => ra_steps, "dec" => dec_steps},
          # the practical margin: how far the camera's reading of a step strays from the command
          "step_error_deg" => %{"ra" => step_error(ra_steps), "dec" => step_error(dec_steps)}
        }

      {:error, _} ->
        nil
    end
  end

  defp pair_fit(_, _, _, _), do: nil

  # largest angle between any two of the remembered polar-axis directions
  defp spread_deg(dirs) when length(dirs) < 2, do: nil

  defp spread_deg(dirs) do
    for a <- dirs, b <- dirs, a != b do
      [ax, ay, az] = a
      [bx, by, bz] = b
      :math.acos(min(1.0, abs(ax * bx + ay * by + az * bz))) * 180 / :math.pi()
    end
    |> Enum.max()
    |> Float.round(1)
  end

  # rms over the sweep of (measured − commanded), after removing the constant offset of the reference frame
  defp step_error(steps) do
    diffs = Enum.map(steps, &(&1["measured_deg"] - &1["commanded_deg"]))
    mean = Enum.sum(diffs) / max(length(diffs), 1)
    Float.round(:math.sqrt(Enum.sum(Enum.map(diffs, &((&1 - mean) * (&1 - mean)))) / max(length(diffs), 1)), 2)
  end

  # the fit plus two projected points on the axis so the page can draw it
  defp fit_json(f, cam) do
    {px, py, pz} = f.point
    {ax, ay, az} = f.dir
    proj = fn {x, y, z} -> [cam.f * x / z + cam.cx, cam.f * y / z + cam.cy] end
    p1 = proj.({px - ax * 0.4, py - ay * 0.4, pz - az * 0.4})
    p2 = proj.({px + ax * 0.4, py + ay * 0.4, pz + az * 0.4})

    %{
      "dir" => [ax, ay, az],
      "point" => [px, py, pz],
      "line" => [p1, p2],
      "image_angle_deg" => Float.round(f.image_angle_deg, 1),
      "tilt_deg" => Float.round(f.tilt_deg, 1),
      "image_angle_sd_deg" => f.image_angle_sd_deg && Float.round(f.image_angle_sd_deg, 2),
      "tilt_sd_deg" => f.tilt_sd_deg && Float.round(f.tilt_sd_deg, 2),
      "bootstrap_sd_deg" => f.bootstrap_sd_deg && Float.round(f.bootstrap_sd_deg, 2),
      "tilt_ambiguous" => f.tilt_ambiguous,
      "rms_px" => Float.round(f.rms_px, 2),
      "n" => f.n,
      "sense" => f.sense
    }
  end

  defp sweep_words(%{"fit" => nil}), do: "not enough spots to fit"
  defp sweep_words(%{"fit" => f}), do: "#{f["n"]} spots · in picture #{f["image_angle_deg"]}° · tilt #{f["tilt_deg"]}° · ±#{f["bootstrap_sd_deg"] || f["tilt_sd_deg"]}° · rms #{f["rms_px"]} px"
  defp sweep_words(_), do: "?"

  defp streaming? do
    match?(%{source: :stream}, Watch.status())
  end

  defp camera_ready do
    case Watch.status() do
      %{tool: nil} -> {:error, "no camera tool on this machine"}
      _ -> :ok
    end
  end

  defp capture(parent, step, after_at \\ nil, tries \\ 0) do
    send(parent, {:step, step})

    case Watch.capture() do
      %{at: at} ->
        cond do
          # while video runs, stills come from the encoder every few seconds:
          # make sure this one was taken after the move, not before it
          after_at && DateTime.compare(at, after_at) != :gt && tries < 20 ->
            Process.sleep(1_000)
            capture(parent, step, after_at, tries + 1)

          after_at && DateTime.compare(at, after_at) != :gt ->
            {:error, "camera gave no new frame"}

          true ->
            case Watch.latest() do
              %{jpeg: jpeg} ->
                name = Watch.history(limit: 1) |> List.first() |> then(&(&1 && &1.name))
                with {:ok, frame} <- Frame.from_binary(jpeg, @factor), do: {:ok, frame, name, at}

              _ ->
                {:error, "no frame"}
            end
        end

      {:error, why} ->
        {:error, "capture failed: #{why}"}
    end
  end

  defp axis(parent, ref, axis, delta, before) do
    send(parent, {:step, {:move, axis}})

    with :ok <- Mount.goto_relative(ref, axis, delta),
         :ok <- settle(ref, axis),
         # the encoder's still is one frame every five seconds and its file time
         # can lead its content: when stills come from the stream, insist on
         # one taken a full period after the tube stopped
         after_at = DateTime.add(DateTime.utc_now(), if(streaming?(), do: 5, else: 0), :second),
         {:ok, after_frame, after_name, _} <- capture(parent, {:capture, axis}, after_at),
         :ok <- Mount.goto_relative(ref, axis, -delta),
         :ok <- settle(ref, axis) do
      send(parent, {:step, {:analyse, axis}})
      raw = Flow.between(before, after_frame, search: 8)
      # only a slide has a "crowd" to disagree with; a turn fans out on purpose
      raw_fit = Pivot.fit(raw)
      vectors = if raw_fit && raw_fit.coherence > 0.6, do: Pivot.coherent(raw), else: raw
      fit = Pivot.fit(vectors)
      {:ok, %{vectors: vectors, dropped: length(raw) - length(vectors), fit: fit, line: Pivot.axis_line(vectors), frame_after: after_name, words: Pivot.words(fit)}}
    else
      {:error, :limit} -> {:error, "#{axis}: soft limit — move the mount away from a limit and try again"}
      {:error, e} -> {:error, "#{axis}: #{inspect(e)}"}
    end
  end

  # Wait for the goto to land, then a beat for the tube to stop swaying. A
  # goto starts on the driver's next poll, so "not running" a moment after
  # asking means nothing; the driver's goto_pending flag is set at once and
  # cleared only when the goto has landed — that is what we wait on.
  defp settle(ref, axis, waited \\ 0) do
    Process.sleep(250)

    case Mount.snapshot(ref) do
      %{axes: axes} ->
        ax = axes[axis]
        busy = ax.running or Map.get(ax, :goto_pending, false)

        cond do
          busy and waited < 40_000 -> settle(ref, axis, waited + 250)
          busy -> {:error, "#{axis} still moving after 40 s"}
          true -> Process.sleep(@settle_ms); :ok
        end

      _ ->
        {:error, "no snapshot"}
    end
  end

  defp summary(%{fit: nil}), do: "no motion seen"
  defp summary(%{fit: f}), do: "#{f.n} blocks · quality #{Float.round(f.quality, 2)} · coherence #{Float.round(f.coherence, 2)}"

  # settings are JSON: atoms → strings, tuples → lists
  defp stringify(%{ra: ra, dec: dec} = res) do
    res
    |> Map.delete(:ra)
    |> Map.delete(:dec)
    |> Map.put("ra", axis_json(ra))
    |> Map.put("dec", axis_json(dec))
  end

  defp axis_json(%{vectors: vs, fit: fit, line: line, dropped: dropped, frame_after: fa, words: words}) do
    %{
      "vectors" => Enum.map(vs, &%{"x" => &1.x, "y" => &1.y, "dx" => &1.dx, "dy" => &1.dy}),
      "dropped" => dropped,
      "line" => line && Map.new(line, fn {k, v} -> {Atom.to_string(k), v} end),
      "fit" => fit && Map.new(fit, fn {k, v} -> {Atom.to_string(k), v} end),
      "frame_after" => fa,
      "words" => words
    }
  end

  defp announce(s) do
    Telescope.broadcast(@topic, {:optical, Map.take(s, [:id, :step, :error]) |> Map.put(:running, s.task != nil)})
    s
  end
end
