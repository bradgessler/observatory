defmodule Controller.CameraLive do
  @moduledoc """
  The camera's own page: which camera, timed stills and their interval, what
  sizes it can do, which encoder video uses, and — when something fails —
  the last lines ffmpeg said. The Watch page stays a picture; this is where
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

    {:ok, socket |> assign(night: Settings.get("night", false), notice: nil, rungs: nil, fps: Settings.get("video_fps", 30), size: Settings.get("video_quality", "auto")) |> load()}
  end

  defp load(socket) do
    video =
      try do
        Video.status()
      catch
        :exit, _ -> %{state: :off, error: "video app not running", log: [], encoder: nil, supported_modes: nil, quality: nil}
      end

    assign(socket, status: Watch.status(), devices: Watch.devices(), video: video, summary: Watch.history_summary())
  end

  @impl true
  def handle_info({:watch, _}, socket), do: {:noreply, load(socket)}
  def handle_info({:video, _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
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
      :exit, _ -> {:noreply, assign(socket, notice: "video app not running")}
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
        <.back navigate={~p"/controls/watch"} label="Watch" />
        <.title>Camera</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card title="Camera">
        <.kv label="Capture tool" value={to_string(@status.tool || "none — brew install imagesnap, or ffmpeg")} />
        <form :if={@devices != []} phx-change="select" class="row">
          <select name="device" class="field" disabled={@video.state != :off}>
            <option :for={d <- @devices} value={d} selected={d == @status.device}>{d}</option>
          </select>
        </form>
        <.hint :if={@video.state != :off}>Stop the video to change camera.</.hint>
      </.card>

      <.card title="Timed Stills">
        <div class="seg" role="radiogroup" aria-label="timed stills">
          <button class={["seg-opt", !@status.enabled && "on"]} phx-click="timed" phx-value-on="false" role="radio" aria-checked={to_string(!@status.enabled)}>Off</button>
          <button class={["seg-opt", @status.enabled && "on"]} phx-click="timed" phx-value-on="true" role="radio" aria-checked={to_string(@status.enabled)}>Every {div(@status.interval, 1000)} s</button>
        </div>
        <.hint>Watching the Watch page turns these on. Each still is kept for a while (below) so a person or an agent can look back.</.hint>
        <.kv label="Kept" value={"#{@summary.count} frames · #{div(@summary.bytes, 1_048_576)} MB · up to #{@summary.policy.max_frames} frames or #{div(@summary.policy.max_age_s, 60)} min"} />
        <.hint :if={@status.last_error} class="err">Last capture error: {@status.last_error}</.hint>
      </.card>

      <.card title="Video">
        <div class="seg seg-4" role="radiogroup" aria-label="video size">
          <button :for={{lbl, q} <- [{"Auto", "auto"}, {"1K", "1k"}, {"2K", "2k"}, {"4K", "4k"}]} class={["seg-opt", q == @size && "on"]} phx-click="size" phx-value-q={q} role="radio" aria-checked={to_string(q == @size)}>{lbl}</button>
        </div>
        <.hint>Auto takes the best this camera offers up to 1080p. 4K is a choice, not a default — it's four times the work.</.hint>
        <div class="seg seg-3" role="radiogroup" aria-label="frame rate">
          <button :for={f <- Video.HLS.fps_choices()} class={["seg-opt", f == @fps && "on"]} phx-click="fps" phx-value-fps={f} role="radio" aria-checked={to_string(f == @fps)}>{f} fps</button>
        </div>
        <.hint>30 is plenty for watching a mount; 24 saves a little, 60 costs double for no benefit here.</.hint>
        <.kv label="Encoder" value={to_string(@video.encoder || "chosen when video starts")} />
        <.kv label="State" value={"#{@video.state}#{if @video.quality, do: " · #{@video.quality}"}"} />
        <.row>
          <.btn phx-click="probe" disabled={@video.state != :off}>What sizes can this camera do?</.btn>
        </.row>
        <ul :if={@rungs} class="checklist">
          <li :for={r <- @rungs}>{r.label} · {Video.Ladder.size_string(r.size)} — {if r.available?, do: "yes", else: "no"}</li>
        </ul>
        <.hint :if={@video.error} class="err">{@video.error}</.hint>
        <pre :if={@video.log != []} class="video-log">{Enum.join(Enum.reverse(@video.log), "\n")}</pre>
        <.hint>HLS from FFmpeg on this machine, 1-second segments. Heavy: on a Pi, run it on a bigger machine.</.hint>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
