defmodule Controller.CameraLive do
  @moduledoc """
  The camera's own page: which camera, timed stills and their interval, what
  sizes it can do, which encoder video uses, and — when something fails —
  the last lines ffmpeg said. The Observatory Camera page stays a picture; this is where
  the knobs and the diagnostics live.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Watch.subscribe()
      Video.subscribe()
      Settings.subscribe()
    end

    {:ok, socket |> assign(page_title: "Observatory Camera · Settings", night: Settings.get("night", false), notice: nil, rungs: nil, fps: Settings.get("video_fps", 30), size: Settings.get("video_quality", "auto")) |> load()}
  end

  defp load(socket) do
    video =
      try do
        Video.status()
      catch
        :exit, _ -> %{state: :off, error: "video app not running", log: [], encoder: nil, supported_modes: nil, quality: nil, fell_back_from: nil}
      end

    assign(socket, status: Watch.status(), devices: Watch.devices(), video: video, summary: Watch.history_summary())
  end

  @impl true
  def handle_info({:watch, _}, socket), do: {:noreply, load(socket)}
  def handle_info({:video, _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("timed", %{"on" => on}, socket) do
    Watch.enable(on == "true")
    {:noreply, load(socket)}
  end

  def handle_event("select", %{"device" => d}, socket) do
    Watch.select(d)
    {:noreply, load(socket)}
  end

  # opens the camera for a moment to ask what it can do
  def handle_event("probe", _, socket) do
    try do
      %{rungs: rungs} = Video.qualities()
      {:noreply, assign(socket, rungs: rungs)}
    catch
      :exit, _ -> {:noreply, assign(socket, notice: "Video app not running")}
    end
  end

  def handle_event("size", %{"q" => q}, socket) do
    Settings.put("video_quality", q)
    if socket.assigns.video.state in [:starting, :streaming, :restarting], do: Video.start(quality: q, fps: socket.assigns.fps)
    {:noreply, socket |> assign(size: q) |> load()}
  end

  def handle_event("fps", %{"fps" => f}, socket) do
    fps = String.to_integer(f)
    Settings.put("video_fps", fps)
    # a running stream picks the new rate up straight away
    if socket.assigns.video.state in [:starting, :streaming, :restarting], do: Video.start(quality: socket.assigns.video.quality, fps: fps)
    {:noreply, socket |> assign(fps: fps) |> load()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="camera" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/observatory"} label="Observatory Camera" />
        <.title>Settings</.title>
        <.actions><.help href={~p"/docs/watch"} label="the observatory camera" /><.stop /></.actions>
      </:header>

      <.card title="Camera">
        <.kv label="Capture tool" value={to_string(@status.tool || "None found on this machine")} />
        <form :if={@devices != []} phx-change="select" class="row">
          <select name="device" class="field" disabled={@video.state != :off} aria-label="which camera">
            <option :for={d <- @devices} value={d} selected={d == @status.device}>{d}</option>
          </select>
        </form>
        <.hint :if={@video.state != :off}>Stop the video to change camera.</.hint>
      </.card>

      <.card title="Timed Stills">
        <.seg label="timed stills">
          <:opt on={!@status.enabled} click="timed" value={%{on: "false"}}>Off</:opt>
          <:opt on={@status.enabled} click="timed" value={%{on: "true"}}>Every {div(@status.interval, 1000)} s</:opt>
        </.seg>
        <.hint>Looking at the Observatory Camera turns these on. Each still is kept for a while (below) so a person or an agent can look back.</.hint>
        <.kv label="Kept" value={"#{@summary.count} frames · #{div(@summary.bytes, 1_048_576)} MB · up to #{@summary.policy.max_frames} frames or #{div(@summary.policy.max_age_s, 60)} min"} />
        <.hint :if={@status.last_error} class="err">Last capture error: {@status.last_error}</.hint>
      </.card>

      <.card title="Video">
        <.seg label="video size">
          <:opt :for={{lbl, q} <- [{"Auto", "auto"}, {"1K", "1k"}, {"2K", "2k"}, {"4K", "4k"}]} on={q == @size} click="size" value={%{q: q}}>{lbl}</:opt>
        </.seg>
        <.hint>Auto is 720p: every camera does it and it's cheap to encode. Bigger is a choice, not a default: 1080p is twice the work, 4K eight times. A size the camera won't deliver falls back one step by itself.</.hint>
        <.seg label="frame rate">
          <:opt :for={f <- Video.HLS.fps_choices()} on={f == @fps} click="fps" value={%{fps: f}}>{f} fps</:opt>
        </.seg>
        <.hint>30 is plenty for watching a mount; 24 saves a little, 60 costs double for no benefit here.</.hint>
        <.kv label="Encoder" value={to_string(@video.encoder || "chosen when video starts")} />
        <.kv label="State" value={"#{@video.state}#{if @video.quality, do: " · #{@video.quality}"}"} />
        <.row>
          <.btn phx-click="probe" disabled={@video.state != :off}>What Sizes Can This Camera Do?</.btn>
        </.row>
        <ul :if={@rungs} class="checklist" aria-label="sizes this camera can do">
          <li :for={r <- @rungs}>{r.label} · {Video.Ladder.size_string(r.size)} · {if r.available?, do: "yes", else: "no"}</li>
        </ul>
        <.hint :if={@video.error} class="err" role="alert">{@video.error}</.hint>
        <pre :if={@video.log != []} class="video-log" aria-label="last lines from the encoder" tabindex="0">{Enum.join(Enum.reverse(@video.log), "\n")}</pre>
        <.hint>HLS from FFmpeg on this machine, 1-second segments. Heavy: on a Pi, run it on a bigger machine.</.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
