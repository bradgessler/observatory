defmodule Video.HLS do
  @moduledoc """
  One FFmpeg, one quality, one HLS playlist on disk. Owns the OS process as
  a port (through `priv/wrap.sh`, so the process dies with the BEAM), watches
  the playlist appear, keeps the last lines of ffmpeg's stderr for the page
  to show when something goes wrong, and writes a still every few seconds
  that `Watch` can pick up while the camera is busy streaming.

  Files: `~/.observatory/video/<quality>/index.m3u8` + `segNNNNN.ts`. The
  playlist keeps the last ten 1-second segments, each stamped with wall-clock
  time (EXT-X-PROGRAM-DATE-TIME) so the player can measure its own delay;
  old segments are deleted.
  """
  use GenServer
  require Logger

  alias Video.{Encoder, Ladder, Source}

  @still "still.jpg"
  @still_every_s 5
  @poll_ms 500
  @camera_handoff_ms 2_500
  @default_fps 30
  @fps_choices [24, 30, 60]

  @doc "Frame rates a stream can be asked for."
  def fps_choices, do: @fps_choices
  @warmup_ms 20_000
  @max_restarts 3

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def start(opts \\ []), do: GenServer.call(__MODULE__, {:start, opts}, 10_000)
  def stop, do: GenServer.call(__MODULE__, :stop, 10_000)
  def status, do: GenServer.call(__MODULE__, :status)
  def select(device), do: GenServer.call(__MODULE__, {:select, device})

  @doc "The ladder with `available?` filled in for the selected camera."
  def qualities, do: GenServer.call(__MODULE__, :qualities, 15_000)

  @doc "Latest still the encoder wrote, if streaming and fresh: `{:ok, jpeg, taken_at}` — the file's own time, not now."
  def snapshot do
    case status() do
      %{state: :streaming, quality: q} ->
        path = Path.join(dir(q), @still)

        with {:ok, %{mtime: mtime}} <- File.stat(path, time: :posix),
             true <- System.os_time(:second) - mtime < @still_every_s * 3,
             {:ok, jpeg} when byte_size(jpeg) > 1_000 <- File.read(path) do
          {:ok, jpeg, DateTime.from_unix!(mtime)}
        else
          _ -> {:error, :stale}
        end

      _ ->
        {:error, :not_streaming}
    end
  end

  @doc "Directory for one rung's files."
  def dir(quality), do: Path.join(root(), Atom.to_string(quality))
  def root, do: Application.get_env(:video, :dir) || Path.join([System.user_home!(), ".observatory", "video"])

  # -- server -----------------------------------------------------------------------

  @impl true
  def init(_) do
    Process.flag(:trap_exit, true)

    {:ok,
     %{
       state: :off,
       quality: nil,
       device: nil,
       port: nil,
       os_pid: nil,
       started_at: nil,
       ready: false,
       restarts: 0,
       log: [],
       error: nil,
       encoder: nil,
       modes: nil,
       fps: @default_fps,
       fell_back_from: nil,
       last_still_hash: nil,
       same_still: 0
     }}
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, public(s), s}

  def handle_call({:select, device}, _from, s), do: {:reply, :ok, %{s | device: device, modes: nil}}

  def handle_call(:qualities, _from, s) do
    modes = s.modes || Source.impl().modes(s.device)
    list = Enum.map(Ladder.rungs(), &Map.put(&1, :available?, Ladder.available?(&1, modes)))
    {:reply, %{rungs: list, modes: modes}, %{s | modes: modes}}
  end

  def handle_call({:start, opts}, _from, s) do
    {quality, s} =
      case opts[:quality] || :auto do
        a when a in [:auto, "auto"] -> auto_rung(s)
        q -> {Ladder.parse(q), s}
      end

    cond do
      is_nil(quality) ->
        {:reply, {:error, :unknown_quality}, s}

      is_nil(System.find_executable("ffmpeg")) ->
        {:reply, {:error, :no_ffmpeg}, %{s | error: "ffmpeg not installed (brew install ffmpeg / apt install ffmpeg)"}}

      true ->
        fps = if opts[:fps] in @fps_choices, do: opts[:fps], else: s.fps
        # announce first: Watch stops grabbing stills the moment it hears
        # :starting, and a grab already in flight needs a couple of seconds
        # to let go of the camera — two processes on it at once corrupts the
        # stream for its whole life
        # a fresh Play gets a fresh restart budget
        s = %{s | fps: fps, fell_back_from: nil, quality: quality.id, state: :starting, error: nil, restarts: 0} |> kill() |> announce()
        Process.send_after(self(), {:launch, quality.id}, @camera_handoff_ms)
        {:reply, :ok, s}
    end
  end

  def handle_call(:stop, _from, s) do
    Telescope.Events.emit(:video, :stop, %{quality: s.quality})
    {:reply, :ok, s |> kill() |> Map.merge(%{state: :off, error: nil, fell_back_from: nil}) |> announce()}
  end

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = s) do
    lines = data |> String.split(~r/[\r\n]+/, trim: true) |> Enum.map(&String.slice(&1, 0, 300))
    {:noreply, %{s | log: Enum.take(lines ++ s.log, 30)}}
  end

  def handle_info({port, {:exit_status, code}}, %{port: port} = s) do
    reason = "ffmpeg exited (#{code}): #{first_interesting(s.log)}"
    Logger.warning("video: #{reason}")
    s = %{s | port: nil, os_pid: nil, ready: false}

    # a camera that dies mid-stream gets a few retries; one that never starts does not
    if s.restarts < @max_restarts and s.state == :streaming do
      Process.send_after(self(), :relaunch, 1_000)
      {:noreply, announce(%{s | state: :restarting, error: reason, restarts: s.restarts + 1})}
    else
      {:noreply, announce(%{s | state: :error, error: reason})}
    end
  end

  def handle_info({:launch, q}, %{state: :starting, port: nil} = s), do: {:noreply, launch(s, q)}
  def handle_info({:launch, _}, s), do: {:noreply, s}
  def handle_info(:relaunch, %{state: :restarting, quality: q, restarts: r} = s) when r <= @max_restarts, do: {:noreply, launch(s, q)}
  def handle_info(:relaunch, %{state: :restarting} = s), do: {:noreply, announce(%{s | state: :error, error: "the camera keeps freezing — giving up; unplug and replug it, then Play again"})}
  def handle_info(:relaunch, s), do: {:noreply, s}

  def handle_info(:poll, %{state: :starting} = s) do
    cond do
      playlist_ready?(s.quality) ->
        Process.send_after(self(), :frozen_check, @still_every_s * 1_000)
        {:noreply, announce(%{s | state: :streaming, ready: true, error: nil, last_still_hash: nil, same_still: 0})}

      System.monotonic_time(:millisecond) - s.started_at > @warmup_ms ->
        reason = "no playlist after #{div(@warmup_ms, 1000)} s: #{first_interesting(s.log)}"

        case lower(s.quality) do
          # the camera would not deliver this size: try the next one down, once
          lower when lower != nil and :erlang.map_get(:fell_back_from, s) == nil ->
            Logger.warning("video: #{s.quality} produced nothing (#{reason}); falling back to #{lower}")
            {:noreply, s |> kill() |> Map.put(:fell_back_from, s.quality) |> launch(lower)}

          _ ->
            {:noreply, s |> kill() |> Map.merge(%{state: :error, error: reason}) |> announce()}
        end

      true ->
        Process.send_after(self(), :poll, @poll_ms)
        {:noreply, s}
    end
  end

  def handle_info(:poll, s), do: {:noreply, s}

  # The capture can freeze on one buffer (a USB hiccup, a camera reset): ffmpeg
  # keeps encoding it forever and every still is the same bytes. Watch the
  # still's hash; three identical in a row on a scene that has a live camera
  # means frozen — restart the encoder rather than stream a photograph.
  def handle_info(:frozen_check, %{state: :streaming} = s) do
    Process.send_after(self(), :frozen_check, @still_every_s * 1_000)
    hash = still_hash(s.quality)
    same = if hash != nil and hash == s.last_still_hash, do: s.same_still + 1, else: 0

    if same >= 3 do
      Logger.warning("video: still unchanged #{same} times — capture frozen, restarting encoder")
      Telescope.Events.emit(:video, :frozen, %{quality: s.quality})
      s = s |> kill() |> Map.merge(%{state: :restarting, error: "camera froze — restarting", last_still_hash: nil, same_still: 0, restarts: s.restarts + 1})
      Process.send_after(self(), :relaunch, 2_500)
      {:noreply, announce(s)}
    else
      {:noreply, %{s | last_still_hash: hash, same_still: same}}
    end
  end

  def handle_info(:frozen_check, s), do: {:noreply, s}
  def handle_info({:EXIT, _port, _}, s), do: {:noreply, s}
  def handle_info(_, s), do: {:noreply, s}

  @impl true
  def terminate(_reason, s), do: kill(s)

  # -- ffmpeg ------------------------------------------------------------------------

  defp launch(s, quality) do
    rung = Ladder.get(quality)
    out = dir(quality)
    File.rm_rf(out)
    File.mkdir_p!(out)
    encoder = Encoder.pick()
    ffmpeg = System.find_executable("ffmpeg")

    args =
      ~w(-hide_banner -nostdin -loglevel warning) ++
        Source.impl().input_args(s.device, rung.size, s.fps) ++
        Encoder.args(encoder, rung.kbps) ++
        # one keyframe per second = one per segment
        ~w(-g #{s.fps} -keyint_min #{s.fps} -an) ++
        # 1 s segments, wall-clock stamped, so a player can say how far behind it is
        ~w(-f hls -hls_time 1 -hls_list_size 10 -hls_flags delete_segments+independent_segments+program_date_time -hls_segment_filename) ++
        [Path.join(out, "seg%05d.ts"), Path.join(out, "index.m3u8")] ++
        ~w(-map 0:v -vf fps=1/#{@still_every_s} -q:v 3 -f image2 -update 1 -atomic_writing 1) ++
        [Path.join(out, @still)]

    Logger.info("video: starting #{quality} via #{encoder}: ffmpeg #{Enum.join(args, " ")}")
    Telescope.Events.emit(:video, :start, %{quality: quality, encoder: encoder, fps: s.fps})

    port =
      Port.open({:spawn_executable, wrapper()}, [
        :binary,
        :exit_status,
        :stderr_to_stdout,
        :use_stdio,
        args: [ffmpeg | args]
      ])

    os_pid = Keyword.get(Port.info(port), :os_pid)
    Process.send_after(self(), :poll, @poll_ms)

    announce(%{
      s
      | state: :starting,
        quality: quality,
        port: port,
        os_pid: os_pid,
        started_at: System.monotonic_time(:millisecond),
        ready: false,
        log: [],
        error: nil,
        encoder: encoder
    })
  end

  # Auto: the largest rung this camera reports, capped at 1K. Every camera
  # does 720p, it is cheap to encode on a small machine, and it is plenty for
  # watching a mount; bigger sizes are a choice on the Camera page. (Some
  # cameras advertise 1080p and then deliver frames without timestamps.)
  @auto_cap :"1k"
  defp auto_rung(s) do
    modes = s.modes || Source.impl().modes(s.device)
    s = %{s | modes: modes}

    rung =
      case modes do
        :unknown ->
          Ladder.get(:"1k")

        list ->
          Ladder.rungs()
          |> Enum.take_while(&(&1.id != @auto_cap))
          |> Kernel.++([Ladder.get(@auto_cap)])
          |> Enum.filter(&Ladder.available?(&1, list))
          |> List.last()
          |> Kernel.||(Ladder.get(:"1k"))
      end

    {rung, s}
  end

  # Closing the port closes the wrapper's stdin; it sends ffmpeg SIGINT.
  defp kill(%{port: nil} = s), do: s

  defp kill(%{port: port} = s) do
    try do
      Port.close(port)
    rescue
      _ -> :ok
    end

    # belt and braces: the wrapper's child, if it is still around a beat later
    if s.os_pid, do: spawn(fn -> Process.sleep(1_500); System.cmd("pkill", ["-INT", "-P", to_string(s.os_pid)], stderr_to_stdout: true) end)
    %{s | port: nil, os_pid: nil, ready: false}
  end

  defp wrapper, do: Path.join(:code.priv_dir(:video), "wrap.sh")

  defp still_hash(q) do
    case File.read(Path.join(dir(q), @still)) do
      {:ok, bin} -> :erlang.phash2(bin)
      _ -> nil
    end
  end

  defp lower(q) do
    ids = Ladder.ids()
    case Enum.find_index(ids, &(&1 == q)) do
      i when is_integer(i) and i > 0 -> Enum.at(ids, i - 1)
      _ -> nil
    end
  end

  # Two segments in the playlist is enough for a player to start.
  defp playlist_ready?(quality) do
    case File.read(Path.join(dir(quality), "index.m3u8")) do
      {:ok, bin} -> length(Regex.scan(~r/^seg\d+\.ts$/m, bin)) >= 2
      _ -> false
    end
  end

  defp first_interesting(log) do
    log
    |> Enum.reverse()
    |> Enum.find("no output", &(&1 =~ ~r/error|not supported|Supported modes|denied|busy|No such|Invalid|failed/i))
  end

  defp public(s) do
    %{
      state: s.state,
      quality: s.quality,
      device: s.device,
      ready: s.ready,
      error: s.error,
      encoder: s.encoder,
      fps: Map.get(s, :fps, @default_fps),
      # Map.get: a hot reload must never crash a running encoder over a new key
      fell_back_from: Map.get(s, :fell_back_from),
      playlist: if(s.ready, do: "#{s.quality}/index.m3u8"),
      log: Enum.take(s.log, 5),
      supported_modes: s.modes,
      since: s.started_at
    }
  end

  defp announce(s) do
    Telescope.broadcast("video", {:video, public(s)})
    s
  end
end
