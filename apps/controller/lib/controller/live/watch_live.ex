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

  defp video_words(%{state: :off}), do: "off"
  defp video_words(%{state: :starting}), do: "starting"
  defp video_words(%{state: :restarting}), do: "restarting"
  defp video_words(%{state: :streaming, quality: q}), do: "live · #{q}"
  defp video_words(%{state: :error}), do: "error"
  defp video_words(_), do: "?"

  defp pinned_entry(nil, _), do: nil
  defp pinned_entry(name, history), do: Enum.find(history, &(&1.name == name))

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="watch" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/watch"} label="bench" />
        <.title>watch</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card>
        <:aside>
          <.badge on={@status.enabled}>{if @status.enabled, do: "live · every #{div(@status.interval, 1000)} s", else: "paused"}</.badge>
        </:aside>
        <% pin = pinned_entry(@pinned, @history) %>
        <div class="watch-frame">
          <img :if={pin} src={~p"/watch/frames/#{pin.name}"} alt={"frame of the telescope from #{Calendar.strftime(pin.at, "%H:%M:%S")} UTC"} />
          <img :if={!pin and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
          <.hint :if={!pin and !@frame}>No frame yet. {if @status.tool, do: "Tap Capture.", else: "No capture tool on this machine (brew install imagesnap)."}</.hint>
        </div>
        <.hint :if={pin}><b>held on</b> {Calendar.strftime(pin.at, "%H:%M:%S")} UTC · {div(pin.bytes, 1024)} KB · <a href="#" phx-click="pin">back to live</a></.hint>
        <.hint :if={!pin and @frame}>{Calendar.strftime(@frame.at, "%H:%M:%S")} UTC · {@frame.device} · {div(@frame.bytes, 1024)} KB</.hint>

        <%!-- the recent past, newest first; tap one to hold it, tap again for live --%>
        <nav :if={@history != []} class="watch-strip" aria-label="recent frames">
          <a :for={e <- @history} href="#" class={e.name == @pinned && "on"} phx-click="pin" phx-value-name={if e.name == @pinned, do: nil, else: e.name}>
            <img src={~p"/watch/frames/#{e.name}"} alt="" loading="lazy" />
            <time datetime={DateTime.to_iso8601(e.at)}>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
          </a>
        </nav>
        <.hint :if={@summary.count > 0}>
          keeping {@summary.count} frames · {div(@summary.bytes, 1_048_576)} MB · back to {Calendar.strftime(@summary.oldest, "%H:%M:%S")} UTC
          (up to {@summary.policy.max_frames} frames or {div(@summary.policy.max_age_s, 60)} min, on disk)
        </.hint>
        <.row>
          <.btn phx-click="capture" disabled={is_nil(@status.tool)}>Capture</.btn>
          <.btn phx-click="live" on={@status.enabled} disabled={is_nil(@status.tool)}>{if @status.enabled, do: "Pause", else: "Live"}</.btn>
        </.row>
        <form :if={@devices != []} phx-change="select" class="row">
          <select name="device" class="field">
            <option :for={d <- @devices} value={d} selected={d == @status.device}>{d}</option>
          </select>
        </form>
        <.hint :if={@status.last_error}>last error: {@status.last_error}</.hint>
      </.card>

      <.card title="Video">
        <:aside>
          <.badge on={@video.state == :streaming} warn={@video.state == :error}>{video_words(@video)}</.badge>
        </:aside>
        <div class="video-frame">
          <%!-- data-src appears only once the playlist exists; the hook follows it --%>
          <video id="video-feed" phx-hook="Hls" data-src={@video.playlist && "/video/#{@video.playlist}"} playsinline muted autoplay controls={@video.ready}></video>
          <.hint :if={@video.state == :off}>Off. Stills above keep coming either way.</.hint>
          <.hint :if={@video.state in [:starting, :restarting]}>Warming up the encoder…</.hint>
          <.hint :if={@video.state == :error}>{@video.error}</.hint>
          <.hint :if={@player && elem(@player, 0) == "unsupported"}>This browser can't play HLS, even with hls.js. Safari, Chrome, Firefox and Edge all can.</.hint>
          <.hint :if={@player && elem(@player, 0) == "error"}>Player error: {elem(@player, 1)}</.hint>
        </div>
        <div class="seg seg-2" role="radiogroup" aria-label="video feed">
          <button class={["seg-opt", @video.state == :off && "on"]} phx-click="stream" phx-value-on="false" aria-checked={to_string(@video.state == :off)} role="radio">Off</button>
          <button class={["seg-opt", @video.state != :off && "on"]} phx-click="stream" phx-value-on="true" aria-checked={to_string(@video.state != :off)} role="radio">Stream</button>
        </div>
        <div class="seg seg-3" role="radiogroup" aria-label="quality">
          <button
            :for={r <- (if @rungs == [], do: Video.Ladder.rungs() |> Enum.map(&Map.put(&1, :available?, true)), else: @rungs)}
            class={["seg-opt", Atom.to_string(r.id) == @quality && "on"]}
            phx-click="quality"
            phx-value-q={r.id}
            disabled={!r.available?}
            role="radio"
            aria-checked={to_string(Atom.to_string(r.id) == @quality)}
          >{r.label}<small>{Video.Ladder.size_string(r.size)}</small></button>
        </div>
        <.hint :if={is_list(@video.supported_modes) and Enum.any?(@rungs, &(!&1.available?))}>
          This camera tops out at {@video.supported_modes |> Enum.max_by(&elem(&1, 0)) |> Video.Ladder.size_string()}; greyed rungs aren't offered.
        </.hint>
        <.hint>HLS from FFmpeg on the server{if @video.encoder, do: " (#{@video.encoder})"}; about 6–10 s behind. Heavy: on a Pi, run this on a bigger machine.</.hint>
        <pre :if={@video.state == :error and @video.log != []} class="video-log">{Enum.join(Enum.reverse(@video.log), "\n")}</pre>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
