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
      player: socket.assigns[:player]
    )
  end

  defp safe_video do
    try do
      Video.status()
    catch
      :exit, _ -> %{state: :off, quality: nil, ready: false, error: "video app not running", playlist: nil, log: [], encoder: nil, supported_modes: nil, fell_back_from: nil}
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

  def handle_event("player", %{"state" => st} = p, socket), do: {:noreply, assign(socket, player: {st, p["detail"]})}

  # one segmented control says it all: Off = stills, a rung = video at that size
  def handle_event("mode", %{"m" => "off"}, socket) do
    Video.stop()
    {:noreply, assign(socket, player: nil, tele: nil, video: safe_video())}
  end

  def handle_event("mode", %{"m" => "live"}, socket) do
    case Video.start(quality: Settings.get("video_quality", "auto"), fps: Settings.get("video_fps", 30)) do
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

  defp size_words(q) do
    case Video.Ladder.get(q) do
      %{size: {_, h}} -> "#{h}p"
      _ -> to_string(q)
    end
  end

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

  @impl true
  def render(assigns) do
    assigns = assign(assigns, busy: busy?(assigns.video))

    ~H"""
    <.page id="watch" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/watch"} label="Bench" />
        <.title>Watch</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <%!-- one picture: the latest still, or the video once it plays --%>
      <div class="watch-frame">
        <video :if={@video.playlist} id="video-feed" phx-hook="Hls" data-src={"/video/#{@video.playlist}"} playsinline muted autoplay controls></video>
        <img :if={!@video.playlist and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
        <div :if={!@video.playlist and !@frame} class="watch-empty"></div>
        <button :if={!@busy} class="play-btn" phx-click="mode" phx-value-m="live" aria-label="play live video">Play</button>
      </div>

      <%!-- one quiet line: what this picture is --%>
      <p class={["watch-cap", @video.state == :streaming && "live", @video.state == :error && "err"]} aria-live="polite">
        <%= cond do %>
          <% @video.state == :streaming -> %>
            Live · {size_words(@video.quality)}{if @video.fell_back_from, do: " (#{@video.fell_back_from} gave no picture)", else: ""} · {behind_words(@tele)}{fps_words(@tele)}
          <% @video.state in [:starting, :restarting] -> %>
            Starting video · last still meanwhile
          <% @video.state == :error -> %>
            Video didn't start — showing stills · <.link navigate={~p"/controls/watch/camera"}>why</.link>
          <% @player && elem(@player, 0) in ["unsupported", "noscript", "error"] -> %>
            This browser couldn't play the video
          <% @frame -> %>
            Still · {age_words(@frame, @now)}{if @status.enabled, do: " · every #{div(@status.interval, 1000)} s", else: ""}
          <% true -> %>
            {if @status.tool, do: "No picture yet", else: "No camera tool on this machine"}
        <% end %>
      </p>

      <%!-- no mode to pick: the still is what you see; Play starts video, Stop returns --%>
      <.row :if={@busy}>
        <.btn phx-click="mode" phx-value-m="off">Stop video · back to stills</.btn>
      </.row>

      <p class="watch-links">
        <.link navigate={~p"/controls/watch/frames"}>Recent Frames{if @summary.count > 0, do: " · #{@summary.count}"}</.link>
        <.link navigate={~p"/controls/watch/camera"}>Camera</.link>
      </p>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
