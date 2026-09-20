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
      send(self(), :mount_rescan)
      # the age of the still and the player's delay are shown live
      :timer.send_interval(1_000, :tick)
      # a picture that keeps itself fresh: timed stills go on when someone looks
      if Watch.status().tool, do: Watch.enable(true)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       page_title: "Watch",
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       mount_id: params["id"] || session["id"],
       notice: nil,
       now: DateTime.utc_now(),
       tele: nil,
       refs: %{},
       snap: nil,
       rig: nil,
       axes_on: true,
       # :auto shows the drawing when there is no fresh picture; a person can pin either
       show: :auto
     )
     |> load()}
  end

  @strip 12
  # a picture older than this is not worth looking at; draw the mount instead
  @stale_s 60

  # The drawing stands in when there is nothing fresh to see: no camera, no
  # still yet, or a still that has gone cold. Video always wins.
  defp safe_snap(ref) do
    Mount.snapshot(ref)
  catch
    :exit, _ -> nil
  end

  defp drawing?(_show, _frame, _now, %{playlist: p}) when not is_nil(p), do: false
  defp drawing?(:drawing, _frame, _now, _video), do: true
  defp drawing?(:picture, _frame, _now, _video), do: false
  defp drawing?(:auto, nil, _now, _video), do: true

  defp drawing?(:auto, %{at: at}, now, _video), do: DateTime.diff(now, at) > @stale_s
  defp drawing?(_, _, _, _), do: false

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

  # a sweep with both tilts resolved gives us the mount in camera space
  defp load_rig(%{assigns: %{mount_id: nil}} = socket), do: assign(socket, rig: nil)

  defp load_rig(%{assigns: %{mount_id: id}} = socket) do
    rig =
      case Controller.Optical.AxisScan.result(id) do
        %{"sweep" => %{"ref" => %{"ra" => r, "dec" => d}} = sweep} -> Controller.Optical.Rig.from_sweep(sweep, %{ra: r, dec: d})
        _ -> nil
      end

    assign(socket, rig: rig)
  end

  defp pose(rig, %{axes: %{ra: %{degrees: r}, dec: %{degrees: d}}}) do
    Controller.Optical.Rig.pose(rig, %{ra: r, dec: d}, dec_sign: Controller.Sky.Pointing.pointing().dec_sign)
  end

  defp pose(_, _), do: nil

  defp safe_video do
    try do
      Video.status()
    catch
      :exit, _ -> %{state: :off, quality: nil, ready: false, error: "video app not running", playlist: nil, log: [], encoder: nil, supported_modes: nil, fell_back_from: nil}
    end
  end

  # the mount whose axes we draw: the one asked for, else the first
  def handle_info(:mount_rescan, socket) do
    Process.send_after(self(), :mount_rescan, 5_000)
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    id = if socket.assigns.mount_id in Map.keys(refs), do: socket.assigns.mount_id, else: refs |> Map.keys() |> Enum.sort() |> List.first()
    # take a snapshot now rather than waiting for the next broadcast: the
    # drawing should be there on the first paint
    snap = socket.assigns.snap || if(ref = refs[id], do: safe_snap(ref))
    {:noreply, socket |> assign(refs: refs, mount_id: id, snap: snap) |> load_rig()}
  end

  def handle_info({:mount, snap}, %{assigns: %{mount_id: id}} = socket) when snap.id == id, do: {:noreply, assign(socket, snap: snap)}
  def handle_info({:mount, _}, socket), do: {:noreply, socket}
  def handle_info({:settings, "optical_axes", _}, socket), do: {:noreply, load_rig(socket)}

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
      {:error, why} -> {:noreply, socket |> assign(notice: "Capture failed: #{why}") |> load()}
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
      {:error, why} -> {:noreply, socket |> assign(notice: "Stream: #{why}") |> assign(video: safe_video())}
    end
  end

  # from the Hls hook, once a second while playing: how far behind reality
  # this browser's picture is, and the frame rate it is actually decoding
  def handle_event("telemetry", t, socket) do
    tele = %{latency: num(t["latency"]), fps: num(t["fps"]), exact: t["exact"] == true, paused: t["paused"] == true, at: DateTime.utc_now()}
    {:noreply, assign(socket, tele: tele)}
  end

  def handle_event("axes", %{"on" => on}, socket), do: {:noreply, assign(socket, axes_on: on == "true")}

  def handle_event("show", %{"s" => s}, socket) when s in ~w(auto picture drawing),
    do: {:noreply, assign(socket, show: String.to_existing_atom(s))}

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
      s when s < 2 -> "Just now"
      s when s < 90 -> "#{s} s ago"
      s -> "#{div(s, 60)} min ago"
    end
  end

  defp behind_words(nil), do: "Measuring…"
  defp behind_words(%{latency: nil}), do: "Delay unknown"
  defp behind_words(%{latency: l, exact: exact}), do: "#{if exact, do: "", else: "≥ "}#{:erlang.float_to_binary(l / 1, decimals: 1)} s behind"

  defp fps_words(%{fps: f}) when is_number(f) and f > 0, do: " · #{round(f)} fps"
  defp fps_words(_), do: ""

  defp busy?(video), do: video.state in [:starting, :streaming, :restarting]

  # the one word that changes when the picture's state changes: its own live
  # region, so a screen reader hears "Live" or "Still", not the age every second
  defp state_word(video, player, frame, status) do
    cond do
      video.state == :streaming -> "Live"
      video.state in [:starting, :restarting] -> "Starting video"
      video.state == :error -> "Video didn't start"
      player && elem(player, 0) in ["unsupported", "noscript", "error"] -> "This browser couldn't play the video"
      frame -> "Still"
      status.tool -> "No picture yet"
      true -> "No camera tool on this machine"
    end
  end

  @impl true
  def render(assigns) do
    assigns = assign(assigns, busy: busy?(assigns.video))

    ~H"""
    <.page id="watch" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" />
        <.title>Watch</.title>
        <.actions><.help href={~p"/docs/watch"} label="watching" /></.actions>
      </:header>

      <%!-- one picture: the video, the latest still, or the mount drawn from its encoders --%>
      <% drawn = drawing?(@show, @frame, @now, @video) %>
      <% pose = drawn && @snap && Controller.Components.Scope.pose_from(@snap, Controller.Sky.Pointing.context(@now, @mount_id)) %>
      <div class="watch-frame">
        <div :if={pose} class="watch-drawn">
          <Controller.Components.Scope.scope pose={pose} size={520} label={"#{@mount_id} as drawn from its encoders"} />
        </div>
        <video :if={@video.playlist} id="video-feed" phx-hook="Hls" data-src={"/video/#{@video.playlist}"} playsinline muted autoplay controls aria-label="live video of the telescope"></video>
        <img :if={!drawn and !@video.playlist and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt={"latest still of the telescope, #{age_words(@frame, @now)}"} />
        <div :if={!drawn and !@video.playlist and !@frame} class="watch-empty" aria-hidden="true"></div>
        <button :if={!@busy and !drawn} class="play-btn" phx-click="mode" phx-value-m="live" aria-label="play live video">Play</button>

        <%!-- the mount's axes as the camera sees them, turning with the encoders: solid polar, dashed Dec, long-dashed tube, in the tested inks --%>
        <% p = if @rig && @axes_on && @snap, do: pose(@rig, @snap) %>
        <svg :if={p} viewBox={"0 0 #{@rig.w} #{@rig.h}"} preserveAspectRatio="none" class="axes-overlay live-axes" aria-hidden="true">
          <line x1={elem(elem(p.polar, 0), 0)} y1={elem(elem(p.polar, 0), 1)} x2={elem(elem(p.polar, 1), 0)} y2={elem(elem(p.polar, 1), 1)} stroke="var(--accent)" stroke-width="2.4" />
          <line x1={elem(elem(p.dec, 0), 0)} y1={elem(elem(p.dec, 0), 1)} x2={elem(elem(p.dec, 1), 0)} y2={elem(elem(p.dec, 1), 1)} stroke="var(--on)" stroke-width="2.4" stroke-dasharray="4 4" />
          <line x1={elem(elem(p.tube, 0), 0)} y1={elem(elem(p.tube, 0), 1)} x2={elem(elem(p.tube, 1), 0)} y2={elem(elem(p.tube, 1), 1)} stroke="var(--warn)" stroke-width="2.4" stroke-dasharray="12 6" />
        </svg>
      </div>
      <p :if={@rig} class="watch-cap">
        Axes from the camera's sweep · <span class="ax-ra">polar (solid)</span> · <span class="ax-dec">Dec (dashed)</span> · <span class="ax-tube">tube (long dashes; needs the axes zeroed upright)</span> ·
        <button type="button" class="linklike" phx-click="axes" phx-value-on={to_string(!@axes_on)} aria-pressed={to_string(@axes_on)}>{if @axes_on, do: "hide axes", else: "show axes"}</button>
      </p>

      <p :if={drawn} class="watch-cap">
        Drawn from the encoders{if @frame, do: " · the camera's last picture is #{age_words(@frame, @now)}", else: " · no camera"}
      </p>

      <.seg :if={@status.tool && @frame} label="what to show" class="watch-show">
        <:opt on={@show == :auto} click="show" value={%{s: "auto"}}>Auto</:opt>
        <:opt on={@show == :picture} click="show" value={%{s: "picture"}}>Picture</:opt>
        <:opt on={@show == :drawing} click="show" value={%{s: "drawing"}}>Drawing</:opt>
      </.seg>

      <%!-- one quiet line: what this picture is; only the state word is announced --%>
      <p class={["watch-cap", @video.state == :streaming && "live", @video.state == :error && "err"]}>
        <span role="status" aria-live="polite">{state_word(@video, @player, @frame, @status)}</span>
        <%= cond do %>
          <% @video.state == :streaming -> %>
            · {size_words(@video.quality)}{if @video.fell_back_from, do: " (#{@video.fell_back_from} gave no picture)", else: ""} · {behind_words(@tele)}{fps_words(@tele)}
          <% @video.state in [:starting, :restarting] -> %>
            · last still meanwhile
          <% @video.state == :error -> %>
            · showing stills · <.link navigate={~p"/controls/watch/camera"}>why the video didn't start</.link>
          <% @player && elem(@player, 0) in ["unsupported", "noscript", "error"] -> %>
          <% @frame -> %>
            · {age_words(@frame, @now)}{if @status.enabled, do: " · every #{div(@status.interval, 1000)} s", else: ""}
          <% true -> %>
        <% end %>
      </p>

      <%!-- no mode to pick: the still is what you see; Play starts video, Stop returns --%>
      <.row :if={@busy}>
        <.btn phx-click="mode" phx-value-m="off">Stop Video · Back to Stills</.btn>
      </.row>

      <p class="watch-links">
        <.link navigate={~p"/controls/watch/frames"}>Recent Frames{if @summary.count > 0, do: " · #{@summary.count}"}</.link>
        <.link navigate={~p"/controls/watch/camera"}>Camera</.link>
      </p>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
