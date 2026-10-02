defmodule Controller.ScopeCamera.Stream do
  @moduledoc """
  The telescope camera, kept open: one ffmpeg reading it continuously and
  handing over every frame, gray and halved, as it arrives. Opening a UVC
  camera costs seconds (the SV105C: about 2.5 s) however short the exposure,
  and starting its stream over and over upset the Pi 3's USB controller
  (#106). So the camera is opened once and read until nobody has asked for
  a frame in a while (`idle_ms`, 30 s), then let go.

      Stream.frame("/dev/video0", mode, stack: 4, exposure_ms: 1000)
      # => {:ok, pgm, %{arrived: monotonic_ms}}

  **A frame for you** is the first one whose light all arrived after you
  asked: with `stack: n` (n frames averaged, by ffmpeg's `tmix` as they
  stream), the first whose n frames were all exposed after the call, so a
  picture taken after the mount settles never holds light from before.
  Changing the stack restarts the stream with the new average; exposure and
  gain change while it runs (`Device.set/2`, which a UVC camera takes
  mid-stream), and a caller that just changed them passes `skip:` to let
  the frames still made at the old settings go by (the SV105C needs 3).

  **Supervision.** ffmpeg runs under `Video`'s wrapper, so it dies with the
  BEAM. A stream that exits, or stops sending frames for longer than its
  exposures explain, is restarted, at most 3 times a minute; after that it
  gives up and says so to everyone waiting.
  """
  use GenServer
  require Logger

  alias Controller.ScopeCamera.Device

  @idle_ms 30_000
  @watch_ms 2_000
  @restarts_per_minute 3

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  The next frame from camera `path` read in `mode` whose light all arrived
  after this call: `{:ok, pgm, %{arrived: ms}}` or `{:error, reason}`.
  Options: `stack:` (1), `exposure_ms:` (100), `skip:` frames to let go by
  first (0), `fresh:` (true; false takes the next frame to arrive, light
  from before the call and all, which is what live view wants), `timeout:`
  (sized from the exposure).
  """
  def frame(path, mode, opts \\ []) do
    stack = max(Keyword.get(opts, :stack, 1), 1)
    exposure = Keyword.get(opts, :exposure_ms, 100)
    skip = Keyword.get(opts, :skip, 0)
    # starting the camera, then every frame needed at the camera's own pace (at least 200 ms raw at 1080p)
    frame_ms = max(exposure, 200)
    timeout = Keyword.get(opts, :timeout, round((stack + skip + 2) * frame_ms * 1.5) + 15_000)
    since = System.monotonic_time(:millisecond) + skip * frame_ms
    # not fresh: any frame from now on counts, as if it had no exposure to wait out
    wait = if Keyword.get(opts, :fresh, true), do: stack * max(exposure, 1), else: 0

    GenServer.call(__MODULE__, {:frame, path, mode, stack, exposure, since, wait}, timeout)
  catch
    :exit, {:timeout, _} -> {:error, :timeout}
    :exit, _ -> {:error, :stream_down}
  end

  @doc "Let the camera go now (video wants it, or it was unplugged)."
  def stop do
    GenServer.call(__MODULE__, :stop, 10_000)
  catch
    :exit, _ -> :ok
  end

  @doc "What the stream is doing: `%{running, path, mode, stack, frames, restarts, error}`."
  def status do
    GenServer.call(__MODULE__, :status, 2_000)
  catch
    :exit, _ -> %{running: false}
  end

  # -- the process --------------------------------------------------------------------------

  @impl true
  def init(opts) do
    Process.flag(:trap_exit, true)
    Process.send_after(self(), :watch, @watch_ms)

    {:ok,
     %{
       idle_ms: Keyword.get(opts, :idle_ms, @idle_ms),
       port: nil,
       os_pid: nil,
       key: nil,
       buf: <<>>,
       waiting: [],
       frames: 0,
       started_at: nil,
       last_frame_at: nil,
       last_ask_at: nil,
       exposure: 100,
       restarts: [],
       error: nil
     }}
  end

  @impl true
  def handle_call({:frame, path, mode, stack, exposure, since, wait}, from, s) do
    now = now()
    s = %{s | last_ask_at: now, exposure: exposure}
    s = ensure(s, {path, mode, stack})

    if s.port do
      {:noreply, %{s | waiting: s.waiting ++ [%{from: from, since: since, wait: wait}]}}
    else
      {:reply, {:error, s.error || :stream_down}, s}
    end
  end

  # let go on purpose: a clean slate, restart budget and error included
  def handle_call(:stop, _from, s), do: {:reply, :ok, %{(s |> fail_all(:stopped) |> kill()) | restarts: [], error: nil}}

  def handle_call(:status, _from, s) do
    {path, mode, stack} = s.key || {nil, nil, nil}
    {:reply, %{running: s.port != nil, path: path, mode: mode, stack: stack, frames: s.frames, restarts: length(s.restarts), error: s.error}, s}
  end

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = s), do: {:noreply, split(%{s | buf: s.buf <> data})}

  def handle_info({port, {:exit_status, code}}, %{port: port} = s) do
    Logger.warning("scope camera stream: ffmpeg exited (#{code}) after #{s.frames} frames")
    s = %{s | port: nil, os_pid: nil, buf: <<>>}
    # someone is still waiting: start it again, if it hasn't been doing this all minute
    if s.waiting != [], do: {:noreply, restart(s, {:exited, code})}, else: {:noreply, s}
  end

  def handle_info({:relaunch, key}, %{port: nil, waiting: [_ | _]} = s), do: {:noreply, launch(s, key)}
  def handle_info({:relaunch, _}, s), do: {:noreply, s}

  def handle_info(:watch, s) do
    Process.send_after(self(), :watch, @watch_ms)
    now = now()

    cond do
      # nobody has asked for a while: let the camera go
      s.port && s.waiting == [] && s.last_ask_at && now - s.last_ask_at > s.idle_ms ->
        Logger.info("scope camera stream: idle, closing the camera")
        {:noreply, kill(s)}

      # frames stopped coming, longer than the exposures explain
      s.port && stalled?(s, now) ->
        Logger.warning("scope camera stream: no frame for #{now - (s.last_frame_at || s.started_at)} ms; restarting")
        {:noreply, s |> kill() |> restart(:stalled)}

      true ->
        {:noreply, s}
    end
  end

  def handle_info({:EXIT, _, _}, s), do: {:noreply, s}
  def handle_info(_, s), do: {:noreply, s}

  @impl true
  def terminate(_reason, s), do: kill(s)

  # -- the stream ---------------------------------------------------------------------------

  # running already with this camera, mode and stack: carry on; else (re)start it
  defp ensure(%{port: port, key: key} = s, key) when port != nil, do: s
  defp ensure(s, key), do: s |> kill() |> launch(key)

  defp launch(s, {path, mode, stack} = key) do
    case Keyword.get(Application.get_env(:controller, :scope_camera, []), :ffmpeg) || System.find_executable("ffmpeg") do
      nil ->
        %{s | error: :no_ffmpeg}

      ffmpeg ->
        filters =
          [
            stack > 1 && "tmix=frames=#{stack}",
            "scale='if(gt(iw,1280),iw/2,iw)':'if(gt(iw,1280),ih/2,ih)':flags=area",
            "format=gray"
          ]
          |> Enum.reject(&(&1 == false))
          |> Enum.join(",")

        args = ["-hide_banner", "-loglevel", "error", "-nostdin"] ++ Device.input_args(path, mode) ++ ["-vf", filters, "-f", "image2pipe", "-vcodec", "pgm", "-"]
        Logger.info("scope camera stream: ffmpeg #{Enum.join(args, " ")}")
        port = Port.open({:spawn_executable, wrapper()}, [:binary, :exit_status, args: [ffmpeg | args]])
        os_pid = Keyword.get(Port.info(port) || [], :os_pid)
        %{s | port: port, os_pid: os_pid, key: key, buf: <<>>, frames: 0, started_at: now(), last_frame_at: nil, error: nil}
    end
  end

  defp restart(s, why) do
    now = now()
    recent = Enum.filter(s.restarts, &(now - &1 < 60_000))

    if length(recent) >= @restarts_per_minute do
      Logger.warning("scope camera stream: keeps failing (#{inspect(why)}); giving up")
      %{s | restarts: recent, error: :keeps_failing} |> fail_all(:keeps_failing)
    else
      # a second for the camera to settle after whatever went wrong
      Process.send_after(self(), {:relaunch, s.key}, 1_000)
      %{s | restarts: [now | recent]}
    end
  end

  defp kill(%{port: nil} = s), do: s

  defp kill(%{port: port, os_pid: os_pid} = s) do
    try do
      Port.close(port)
    rescue
      _ -> :ok
    end

    # The wrapper brings ffmpeg down when its stdin closes. Wait for it: a
    # new reader opening the camera while the old one still has it fails
    # ("device busy"), and would count as the camera failing.
    if os_pid, do: gone(os_pid, 50)
    %{s | port: nil, os_pid: nil, buf: <<>>}
  end

  defp gone(os_pid, 0) do
    Logger.warning("scope camera stream: ffmpeg (under #{os_pid}) didn't stop; killing it")
    System.cmd("pkill", ["-KILL", "-P", to_string(os_pid)], stderr_to_stdout: true)
    System.cmd("kill", ["-KILL", to_string(os_pid)], stderr_to_stdout: true)
    :ok
  end

  defp gone(os_pid, tries) do
    case System.cmd("kill", ["-0", to_string(os_pid)], stderr_to_stdout: true) do
      {_, 0} -> Process.sleep(100) && gone(os_pid, tries - 1)
      _ -> :ok
    end
  end

  defp stalled?(s, now) do
    {_, _, stack} = s.key
    allowed = max(s.exposure, 200) * (stack + 2) + 10_000
    now - (s.last_frame_at || s.started_at) > allowed
  end

  # -- frames out of the byte stream ----------------------------------------------------------

  # ffmpeg writes each frame as "P5\n<w> <h>\n255\n" and w x h bytes
  defp split(%{buf: buf} = s) do
    case header(buf) do
      {:ok, hlen, w, h} when byte_size(buf) >= hlen + w * h ->
        size = hlen + w * h
        <<pgm::binary-size(^size), rest::binary>> = buf
        %{s | buf: rest} |> arrived(pgm) |> split()

      {:ok, _, _, _} ->
        s

      :more ->
        s

      :bad ->
        # lost the frame boundary (never seen, but a stream is a stream): resync on the next header
        case :binary.match(buf, "P5\n", scope: {1, byte_size(buf) - 1}) do
          {at, _} -> split(%{s | buf: binary_part(buf, at, byte_size(buf) - at)})
          :nomatch -> %{s | buf: <<>>}
        end
    end
  end

  defp header(<<"P5\n", rest::binary>> = buf) do
    case String.split(rest, "\n", parts: 3) do
      [dims, "255", _] ->
        case String.split(dims, " ") do
          [w, h] -> {:ok, byte_size(buf) - byte_size(rest) + byte_size(dims) + 1 + 4, String.to_integer(w), String.to_integer(h)}
          _ -> :bad
        end

      [_dims, _maxval] ->
        :more

      [_] ->
        :more

      _ ->
        :bad
    end
  rescue
    _ -> :bad
  end

  defp header(buf) when byte_size(buf) < 3, do: :more
  defp header(_), do: :bad

  # a frame: whoever has waited long enough for one this new gets it
  defp arrived(s, pgm) do
    now = now()

    {ready, still} =
      Enum.split_with(s.waiting, fn w ->
        # all `stack` frames in the average were exposed after the ask (100 ms for the trip through USB and ffmpeg)
        now - w.wait - 100 >= w.since
      end)

    for w <- ready, do: GenServer.reply(w.from, {:ok, pgm, %{arrived: now}})
    %{s | waiting: still, frames: s.frames + 1, last_frame_at: now}
  end

  defp fail_all(s, why) do
    for w <- s.waiting, do: GenServer.reply(w.from, {:error, why})
    %{s | waiting: []}
  end

  defp wrapper, do: Path.join(:code.priv_dir(:video), "wrap.sh")
  defp now, do: System.monotonic_time(:millisecond)
end
