defmodule Controller.WatchLive do
  @moduledoc """
  Eyes on the mount: the latest frame from a camera on the server machine,
  refreshed on a timer or on demand. Answers "is it about to wrap a cable?"
  from anywhere.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      Watch.subscribe()
      Video.subscribe()
      Settings.subscribe()
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       mount_id: params["id"] || session["id"],
       notice: nil
     )
     |> load()}
  end

  @strip 12

  defp load(socket) do
    status = Watch.status()

    assign(socket,
      status: status,
      devices: Watch.devices(),
      frame: status.latest,
      stamp: System.unique_integer([:positive]),
      history: Watch.history(limit: @strip),
      summary: Watch.history_summary(),
      # nil = follow the live frame; a name = pinned on one from the strip
      pinned: socket.assigns[:pinned],
      video: safe_video(),
      quality: socket.assigns[:quality] || "1k",
      rungs: socket.assigns[:rungs] || [],
      player: socket.assigns[:player]
    )
  end

  # the ladder probe opens the camera for a moment; only do it on demand
  defp load_rungs(socket) do
    try do
      %{rungs: rungs} = Video.qualities()
      assign(socket, rungs: rungs)
    catch
      :exit, _ -> socket
    end
  end

  defp safe_video do
    try do
      Video.status()
    catch
      :exit, _ -> %{state: :off, quality: nil, ready: false, error: "video app not running", playlist: nil, log: [], encoder: nil, supported_modes: nil}
    end
  end

  @impl true
  def handle_info({:watch, _meta}, socket), do: {:noreply, load(socket)}
  def handle_info({:video, status}, socket), do: {:noreply, assign(socket, video: status)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("capture", _, socket) do
    case Watch.capture() do
      %{} -> {:noreply, load(socket)}
      {:error, why} -> {:noreply, socket |> assign(notice: "capture failed: #{why}") |> load()}
    end
  end

  def handle_event("live", _, socket) do
    Watch.enable(not socket.assigns.status.enabled)
    {:noreply, load(socket)}
  end

  def handle_event("select", %{"device" => d}, socket) do
    Watch.select(d)
    {:noreply, load(socket)}
  end

  def handle_event("quality", %{"q" => q}, socket) do
    socket = assign(socket, quality: q)
    # a running stream follows the picker
    if socket.assigns.video.state in [:starting, :streaming, :restarting], do: Video.start(quality: q)
    {:noreply, socket}
  end

  def handle_event("stream", %{"on" => "true"}, socket) do
    socket = load_rungs(socket)

    case Video.start(quality: socket.assigns.quality) do
      :ok -> {:noreply, assign(socket, player: nil, video: safe_video())}
      {:error, why} -> {:noreply, socket |> assign(notice: "stream: #{why}") |> assign(video: safe_video())}
    end
  end

  def handle_event("stream", _, socket) do
    Video.stop()
    {:noreply, assign(socket, player: nil, video: safe_video())}
  end

  def handle_event("player", %{"state" => st} = p, socket), do: {:noreply, assign(socket, player: {st, p["detail"]})}

  def handle_event("pin", %{"name" => name}, socket), do: {:noreply, assign(socket, pinned: name)}
  def handle_event("pin", _, socket), do: {:noreply, assign(socket, pinned: nil)}

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp video_words(%{state: :off}), do: nil
  defp video_words(%{state: :starting}), do: "warming up the encoder…"
  defp video_words(%{state: :restarting}), do: "encoder dropped out — restarting…"
  defp video_words(%{state: :streaming, quality: q}), do: "live video · #{q}"
  defp video_words(%{state: :error, error: e}), do: e
  defp video_words(_), do: nil

  defp busy?(video), do: video.state in [:starting, :streaming, :restarting]

  defp rungs(assigns) do
    if assigns.rungs == [],
      do: Enum.map(Video.Ladder.rungs(), &Map.put(&1, :available?, true)),
      else: assigns.rungs
  end

  @impl true
  def render(assigns) do
    assigns = assign(assigns, ladder: rungs(assigns), busy: busy?(assigns.video))

    ~H"""
    <.page id="watch" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/watch"} label="bench" />
        <.title>watch</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card>
        <%!-- one picture: the latest still, or the video once it plays. Play sits on top. --%>
        <div class="watch-frame">
          <video :if={@video.playlist} id="video-feed" phx-hook="Hls" data-src={"/video/#{@video.playlist}"} playsinline muted autoplay controls></video>
          <img :if={!@video.playlist and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
          <div :if={!@video.playlist and !@frame} class="watch-empty">
            <.hint>{if @status.tool, do: "No frame yet — tap Capture, or Play.", else: "No capture tool on this machine (brew install imagesnap / ffmpeg)."}</.hint>
          </div>

          <span class={["watch-live", (@video.state == :streaming or @status.enabled) && "on"]}>
            {cond do
              @video.state == :streaming -> "live · #{@video.quality}"
              @busy -> "starting"
              @status.enabled -> "stills · every #{div(@status.interval, 1000)} s"
              @frame -> "still · #{Calendar.strftime(@frame.at, "%H:%M:%S")} UTC"
              true -> "idle"
            end}
          </span>

          <div :if={!@busy} class="play-over">
            <button class="play-btn" phx-click="stream" phx-value-on="true" aria-label="play live video">▶</button>
            <div class="chips" role="radiogroup" aria-label="video quality">
              <button :for={r <- @ladder} class={["chip", Atom.to_string(r.id) == @quality && "on"]} phx-click="quality" phx-value-q={r.id} disabled={!r.available?} role="radio" aria-checked={to_string(Atom.to_string(r.id) == @quality)} title={Video.Ladder.size_string(r.size)}>{r.label}</button>
            </div>
          </div>
          <div :if={@busy} class="play-over playing">
            <button class="chip stop-chip" phx-click="stream" phx-value-on="false">Stop video</button>
            <div class="chips" role="radiogroup" aria-label="video quality">
              <button :for={r <- @ladder} class={["chip", Atom.to_string(r.id) == @quality && "on"]} phx-click="quality" phx-value-q={r.id} disabled={!r.available?} role="radio" aria-checked={to_string(Atom.to_string(r.id) == @quality)} title={Video.Ladder.size_string(r.size)}>{r.label}</button>
            </div>
          </div>
        </div>

        <.hint :if={video_words(@video)} class={@video.state == :error && "err"}>{video_words(@video)}</.hint>
        <.hint :if={@player && elem(@player, 0) == "unsupported"}>This browser can't play HLS, even with hls.js. Safari, Chrome, Firefox and Edge all can.</.hint>
        <.hint :if={@player && elem(@player, 0) == "error"}>Player error: {elem(@player, 1)}</.hint>
        <.hint :if={is_list(@video.supported_modes) and Enum.any?(@ladder, &(!&1.available?))}>
          This camera tops out at {@video.supported_modes |> Enum.max_by(&elem(&1, 0)) |> Video.Ladder.size_string()}; greyed rungs aren't offered.
        </.hint>
        <pre :if={@video.state == :error and @video.log != []} class="video-log">{Enum.join(Enum.reverse(@video.log), "\n")}</pre>

        <.row>
          <.btn phx-click="capture" disabled={is_nil(@status.tool) or @busy}>Capture a still</.btn>
          <.btn phx-click="live" on={@status.enabled} disabled={is_nil(@status.tool)}>{if @status.enabled, do: "Timed stills: on", else: "Timed stills: off"}</.btn>
        </.row>
        <.row>
          <.btn navigate={~p"/controls/watch/frames"}>Recent frames{if @summary.count > 0, do: " · #{@summary.count}"} →</.btn>
        </.row>
        <form :if={@devices != []} phx-change="select" class="row">
          <select name="device" class="field" disabled={@busy}>
            <option :for={d <- @devices} value={d} selected={d == @status.device}>{d}</option>
          </select>
        </form>
        <.hint :if={@status.last_error}>last error: {@status.last_error}</.hint>
        <.hint>Video is HLS from FFmpeg on the server{if @video.encoder, do: " (#{@video.encoder})"}, 6–10 s behind. While it runs, stills come from the encoder and the history keeps filling.</.hint>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
