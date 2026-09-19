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
      # the age of the still and the player's delay are shown live
      :timer.send_interval(1_000, :tick)
      # a picture that keeps itself fresh: timed stills go on when someone looks
      if Watch.status().tool, do: Watch.enable(true)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       mount_id: params["id"] || session["id"],
       notice: nil,
       now: DateTime.utc_now(),
       tele: nil
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
  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}
  def handle_info({:watch, _meta}, socket), do: {:noreply, load(socket)}
  def handle_info({:video, status}, socket), do: {:noreply, assign(socket, video: status, tele: if(status.state == :streaming, do: socket.assigns.tele))}
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
    if socket.assigns.video.state in [:starting, :streaming, :restarting], do: Video.start(quality: q, fps: Settings.get("video_fps", 30))
    {:noreply, socket}
  end

  def handle_event("stream", %{"on" => "true"}, socket) do
    socket = load_rungs(socket)

    case Video.start(quality: socket.assigns.quality, fps: Settings.get("video_fps", 30)) do
      :ok -> {:noreply, assign(socket, player: nil, video: safe_video())}
      {:error, why} -> {:noreply, socket |> assign(notice: "stream: #{why}") |> assign(video: safe_video())}
    end
  end

  def handle_event("stream", _, socket) do
    Video.stop()
    {:noreply, assign(socket, player: nil, video: safe_video())}
  end

  def handle_event("player", %{"state" => st} = p, socket), do: {:noreply, assign(socket, player: {st, p["detail"]})}

  # one segmented control says it all: Off = stills, a rung = video at that size
  def handle_event("mode", %{"m" => "off"}, socket) do
    Video.stop()
    {:noreply, assign(socket, player: nil, tele: nil, video: safe_video())}
  end

  def handle_event("mode", %{"m" => q}, socket) do
    socket = socket |> assign(quality: q) |> load_rungs()

    case Video.start(quality: q, fps: Settings.get("video_fps", 30)) do
      :ok -> {:noreply, assign(socket, player: nil, tele: nil, video: safe_video())}
      {:error, why} -> {:noreply, socket |> assign(notice: "stream: #{why}") |> assign(video: safe_video())}
    end
  end

  # from the Hls hook, once a second while playing: how far behind reality
  # this browser's picture is, and the frame rate it is actually decoding
  def handle_event("telemetry", t, socket) do
    tele = %{latency: num(t["latency"]), fps: num(t["fps"]), exact: t["exact"] == true, paused: t["paused"] == true, at: DateTime.utc_now()}
    {:noreply, assign(socket, tele: tele)}
  end

  def handle_event("pin", %{"name" => name}, socket), do: {:noreply, assign(socket, pinned: name)}
  def handle_event("pin", _, socket), do: {:noreply, assign(socket, pinned: nil)}

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp num(x) when is_number(x), do: x
  defp num(_), do: nil

  defp age_words(%{at: at}, now) do
    case DateTime.diff(now, at, :second) do
      s when s < 2 -> "just now"
      s when s < 90 -> "#{s} s ago"
      s -> "#{div(s, 60)} min ago"
    end
  end

  defp behind_words(nil), do: "measuring…"
  defp behind_words(%{latency: nil}), do: "delay unknown"
  defp behind_words(%{latency: l, exact: exact}), do: "#{if exact, do: "", else: "≥ "}#{:erlang.float_to_binary(l / 1, decimals: 1)} s behind"

  defp fps_words(%{fps: f}) when is_number(f) and f > 0, do: " · #{round(f)} fps"
  defp fps_words(_), do: ""

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
        <%!-- what you are looking at, in one line, always --%>
        <div class={["watch-bar", @video.state == :streaming && "live", @video.state == :error && "err", @busy && @video.state != :streaming && "wait"]} aria-live="polite">
          <%= cond do %>
            <% @video.state == :streaming -> %>
              <b>LIVE VIDEO</b> <span>{@video.quality} · {behind_words(@tele)}{fps_words(@tele)}</span>
            <% @video.state in [:starting, :restarting] -> %>
              <b>STARTING VIDEO</b> <span>{@video.quality} · showing the last still meanwhile</span>
            <% @video.state == :error -> %>
              <b>VIDEO FAILED</b> <span>showing stills</span>
            <% @frame -> %>
              <b>STILL</b> <span>{Calendar.strftime(@frame.at, "%H:%M:%S")} UTC · {age_words(@frame, @now)}{if @status.enabled, do: " · every #{div(@status.interval, 1000)} s", else: ""}</span>
            <% true -> %>
              <b>NO PICTURE</b> <span>{if @status.tool, do: "capture a still or start video", else: "no capture tool on this machine"}</span>
          <% end %>
        </div>

        <%!-- one picture: the latest still, or the video once it plays --%>
        <div class="watch-frame">
          <video :if={@video.playlist} id="video-feed" phx-hook="Hls" data-src={"/video/#{@video.playlist}"} playsinline muted autoplay controls></video>
          <img :if={!@video.playlist and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
          <div :if={!@video.playlist and !@frame} class="watch-empty"></div>
          <button :if={!@busy} class="play-btn" phx-click="mode" phx-value-m={@quality} aria-label="play live video">▶</button>
        </div>

        <%!-- the state is the selected segment: Off means stills --%>
        <div class="seg seg-4" role="radiogroup" aria-label="picture source">
          <button class={["seg-opt", !@busy && "on"]} phx-click="mode" phx-value-m="off" role="radio" aria-checked={to_string(!@busy)}>Stills</button>
          <button
            :for={r <- @ladder}
            class={["seg-opt", @busy and Atom.to_string(r.id) == @quality && "on"]}
            phx-click="mode"
            phx-value-m={r.id}
            disabled={!r.available?}
            role="radio"
            aria-checked={to_string(@busy and Atom.to_string(r.id) == @quality)}
          >{r.label}<small>{Video.Ladder.size_string(r.size)}</small></button>
        </div>

        <.hint :if={@video.state == :error}>The camera didn't start. <.link navigate={~p"/controls/watch/camera"}>Camera page</.link> has the details.</.hint>
        <.hint :if={@player && elem(@player, 0) in ["unsupported", "noscript", "error"]}>This browser couldn't play the video. Safari, Chrome, Firefox and Edge all can.</.hint>

        <.row>
          <.btn phx-click="capture" disabled={is_nil(@status.tool) or @busy}>Capture now</.btn>
          <.btn navigate={~p"/controls/watch/frames"}>Recent frames{if @summary.count > 0, do: " · #{@summary.count}"} →</.btn>
        </.row>
        <.row>
          <.btn navigate={~p"/controls/watch/camera"} class="btn-ghost">Camera, sizes, timing →</.btn>
        </.row>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
