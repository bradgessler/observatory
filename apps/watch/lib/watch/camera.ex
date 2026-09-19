defmodule Watch.Camera do
  @moduledoc """
  Eyes on the hardware. Grabs a still from a camera on this machine, on
  demand or on a timer, keeps the latest frame in memory and broadcasts
  `{:watch, meta}` on `"watch"` so any page (or an agent) can look at it.

  Capture is a short-lived OS command owned by this process:
  `imagesnap` on macOS (brew install imagesnap), `fswebcam` on Linux/Pi.
  No browser is involved; the frame comes from the server.
  """
  use GenServer
  require Logger

  @default_interval_ms 5_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Latest frame: `%{jpeg: binary, at: DateTime, device: name, bytes: n}` or nil."
  def latest, do: :persistent_term.get({__MODULE__, :latest}, nil)

  def status, do: GenServer.call(__MODULE__, :status)
  def capture, do: GenServer.call(__MODULE__, :capture, 20_000)
  def enable(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:enable, on?})
  def select(device) when is_binary(device), do: GenServer.call(__MODULE__, {:select, device})

  @doc "Cameras this machine can see."
  def devices do
    case tool() do
      {:imagesnap, bin} ->
        case System.cmd(bin, ["-l"], stderr_to_stdout: true) do
          {out, 0} ->
            out
            |> String.split("\n")
            |> Enum.flat_map(fn
              "=> " <> name -> [String.trim(name)]
              _ -> []
            end)

          _ ->
            []
        end

      {:fswebcam, _} ->
        Path.wildcard("/dev/video*")

      :none ->
        []
    end
  end

  @impl true
  def init(_) do
    # while video streams, the encoder's still is free: keep the history
    # filling whether or not timed stills are switched on
    Telescope.subscribe("video")
    {:ok, %{enabled: false, interval: @default_interval_ms, device: nil, last_error: nil, frames: 0, streaming: false, video: :free, video_state: :off, video_free_timer: nil}}
  end

  @video_busy [:starting, :streaming, :restarting]

  @impl true
  def handle_call(:status, _from, s) do
    {:reply,
     Map.merge(Map.take(s, [:enabled, :interval, :device, :last_error, :frames, :streaming]), %{
       tool: tool_name(),
       latest: meta(latest()),
       source: if(s.streaming, do: :stream, else: tool_name())
     }), s}
  end

  # success means a frame that was not there before the call: a stale one is
  # never reported as fresh (the axis scan waits on exactly this)
  def handle_call(:capture, _from, s) do
    before = latest()
    s = do_capture(s)

    case latest() do
      %{} = frame when frame != before -> {:reply, meta(frame), s}
      _ -> {:reply, {:error, s.last_error || "no new frame"}, s}
    end
  end

  def handle_call({:enable, on?}, _from, s) do
    if on? and not s.enabled, do: send(self(), :tick)
    {:reply, :ok, %{s | enabled: on?}}
  end

  def handle_call({:select, device}, _from, s), do: {:reply, :ok, %{s | device: device}}

  @impl true
  def handle_info(:tick, %{enabled: false} = s), do: {:noreply, s}

  def handle_info(:tick, s) do
    s = do_capture(s)
    Process.send_after(self(), :tick, s.interval)
    {:noreply, s}
  end

  def handle_info({:video, %{state: state}}, s) do
    streaming? = state == :streaming
    if streaming? and not s.streaming, do: send(self(), :stream_tick)
    busy? = state in @video_busy
    # the encoder takes a moment to release the camera after it is told to
    # stop; a Play that lands inside that moment cancels the release
    if s.video_free_timer, do: Process.cancel_timer(s.video_free_timer)
    timer = if not busy? and s.video == :busy, do: Process.send_after(self(), :video_free, 3_000)
    {:noreply, %{s | streaming: streaming?, video: if(busy?, do: :busy, else: s.video), video_state: state, video_free_timer: timer}}
  end

  # a cancelled timer may already be in the mailbox: never free the camera under a running encoder
  def handle_info(:video_free, %{video_state: st} = s) when st in @video_busy, do: {:noreply, %{s | video_free_timer: nil}}
  def handle_info(:video_free, s), do: {:noreply, %{s | video: :free, video_free_timer: nil}}

  # the stream's own cadence; stops by itself when the stream does
  def handle_info(:stream_tick, %{streaming: false} = s), do: {:noreply, s}

  def handle_info(:stream_tick, s) do
    s = if s.enabled, do: s, else: do_capture(s)
    Process.send_after(self(), :stream_tick, s.interval)
    {:noreply, s}
  end

  # While the encoder holds the camera it also writes a still every few
  # seconds; take that rather than fight it for the device.
  defp do_capture(s) do
    case {streamed_still(), s.video} do
      {{:ok, jpeg, taken_at}, _} ->
        # the encoder's still is up to a few seconds old: stamp it with when
        # it was really taken, so anyone waiting for a frame *after* a move
        # (the axis scan) is not fooled
        if same_as_last?(taken_at), do: %{s | last_error: nil}, else: keep(s, jpeg, "stream", taken_at)

      # never open the camera with a second process while the encoder has it:
      # macOS renegotiates the shared capture format and the stream comes out
      # as interleaved garbage. Wait for the encoder's still instead.
      {:none, :busy} ->
        %{s | last_error: nil}

      {:none, :free} ->
        grab(s)
    end
  end

  defp same_as_last?(taken_at) do
    case latest() do
      %{at: at, device: "stream"} -> DateTime.compare(at, taken_at) == :eq
      _ -> false
    end
  end

  defp streamed_still do
    try do
      case Video.snapshot() do
        {:ok, jpeg, at} -> {:ok, jpeg, at}
        _ -> :none
      end
    catch
      :exit, _ -> :none
    end
  end

  defp grab(s) do
    path = Path.join(System.tmp_dir!(), "watch-#{System.unique_integer([:positive])}.jpg")

    result =
      case tool() do
        {:imagesnap, bin} ->
          args = ["-q", "-w", "0.8"] ++ if(s.device, do: ["-d", s.device], else: []) ++ [path]
          run(bin, args)

        {:fswebcam, bin} ->
          args = ["-q", "--no-banner", "-r", "1280x720"] ++ if(s.device, do: ["-d", s.device], else: []) ++ [path]
          run(bin, args)

        :none ->
          {:error, "no capture tool (brew install imagesnap / apt install fswebcam)"}
      end

    case result do
      :ok ->
        case File.read(path) do
          {:ok, jpeg} when byte_size(jpeg) > 1_000 ->
            File.rm(path)
            keep(s, jpeg, s.device || "default")

          _ ->
            File.rm(path)
            %{s | last_error: "empty frame"}
        end

      {:error, why} ->
        Logger.warning("watch: capture failed: #{why}")
        %{s | last_error: why}
    end
  end

  defp keep(s, jpeg, device, at \\ DateTime.utc_now()) do
    frame = %{jpeg: jpeg, at: at, device: device, bytes: byte_size(jpeg)}
    :persistent_term.put({__MODULE__, :latest}, frame)
    # the recent past on disk; a failure there never loses the live frame
    try do
      Watch.History.put(frame)
    catch
      :exit, why -> Logger.warning("watch: history unavailable: #{inspect(why)}")
    end

    Telescope.broadcast("watch", {:watch, meta(frame)})
    %{s | last_error: nil, frames: s.frames + 1}
  end

  defp run(bin, args) do
    task = Task.async(fn -> System.cmd(bin, args, stderr_to_stdout: true) end)

    case Task.yield(task, 15_000) || Task.shutdown(task, :brutal_kill) do
      {:ok, {_, 0}} -> :ok
      {:ok, {out, code}} -> {:error, "exit #{code}: #{String.trim(out) |> String.slice(0, 200)}"}
      nil -> {:error, "timeout"}
    end
  end

  defp meta(nil), do: nil
  defp meta(frame), do: Map.take(frame, [:at, :device, :bytes])

  defp tool do
    cond do
      bin = System.find_executable("imagesnap") -> {:imagesnap, bin}
      bin = System.find_executable("fswebcam") -> {:fswebcam, bin}
      true -> :none
    end
  end

  defp tool_name do
    case tool() do
      {name, _} -> name
      :none -> nil
    end
  end
end
