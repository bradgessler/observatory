defmodule Video.HLS do
  @moduledoc """
  One FFmpeg, one quality, one HLS playlist on disk. Owns the OS process as
  a port (through `priv/wrap.sh`, so the process dies with the BEAM), watches
  the playlist appear, keeps the last lines of ffmpeg's stderr for the page
  to show when something goes wrong, and writes a still every few seconds
  that `Watch` can pick up while the camera is busy streaming.

  Files: `~/.observatory/video/<quality>/index.m3u8` + `segNNNNN.ts`. The
  playlist keeps the last six 2-second segments; old segments are deleted.
  """
  use GenServer
  require Logger

  alias Video.{Encoder, Ladder, Source}

  @still "still.jpg"
  @still_every_s 5
  @poll_ms 500
  @warmup_ms 20_000
  @max_restarts 3

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def start(opts \\ []), do: GenServer.call(__MODULE__, {:start, opts}, 10_000)
  def stop, do: GenServer.call(__MODULE__, :stop, 10_000)
  def status, do: GenServer.call(__MODULE__, :status)
  def select(device), do: GenServer.call(__MODULE__, {:select, device})

  @doc "The ladder with `available?` filled in for the selected camera."
  def qualities, do: GenServer.call(__MODULE__, :qualities, 15_000)

  @doc "Latest still the encoder wrote, if streaming and fresh."
  def snapshot do
    case status() do
      %{state: :streaming, quality: q} ->
        path = Path.join(dir(q), @still)

        with {:ok, %{mtime: mtime}} <- File.stat(path, time: :posix),
             true <- System.os_time(:second) - mtime < @still_every_s * 3,
             {:ok, jpeg} when byte_size(jpeg) > 1_000 <- File.read(path) do
          {:ok, jpeg}
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
       modes: nil
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
    quality = Ladder.parse(opts[:quality] || :"1k")

    cond do
      is_nil(quality) ->
        {:reply, {:error, :unknown_quality}, s}

      is_nil(System.find_executable("ffmpeg")) ->
        {:reply, {:error, :no_ffmpeg}, %{s | error: "ffmpeg not installed (brew install ffmpeg / apt install ffmpeg)"}}

      true ->
        s = s |> kill() |> launch(quality.id)
        {:reply, :ok, s}
    end
  end

  def handle_call(:stop, _from, s), do: {:reply, :ok, s |> kill() |> Map.merge(%{state: :off, error: nil}) |> announce()}

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

  def handle_info(:relaunch, %{state: :restarting, quality: q} = s), do: {:noreply, launch(s, q)}
  def handle_info(:relaunch, s), do: {:noreply, s}

  def handle_info(:poll, %{state: :starting} = s) do
    cond do
      playlist_ready?(s.quality) ->
        {:noreply, announce(%{s | state: :streaming, ready: true, restarts: 0, error: nil})}

      System.monotonic_time(:millisecond) - s.started_at > @warmup_ms ->
        {:noreply, s |> kill() |> Map.merge(%{state: :error, error: "no playlist after #{div(@warmup_ms, 1000)} s: #{first_interesting(s.log)}"}) |> announce()}

      true ->
        Process.send_after(self(), :poll, @poll_ms)
        {:noreply, s}
    end
  end

  def handle_info(:poll, s), do: {:noreply, s}
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
        Source.impl().input_args(s.device, rung.size) ++
        Encoder.args(encoder, rung.kbps) ++
        ~w(-g 60 -keyint_min 60 -sc_threshold 0 -an) ++
        ~w(-f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+independent_segments -hls_segment_filename) ++
        [Path.join(out, "seg%05d.ts"), Path.join(out, "index.m3u8")] ++
        ~w(-map 0:v -vf fps=1/#{@still_every_s} -q:v 3 -f image2 -update 1 -atomic_writing 1) ++
        [Path.join(out, @still)]

    Logger.info("video: starting #{quality} via #{encoder}: ffmpeg #{Enum.join(args, " ")}")

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
