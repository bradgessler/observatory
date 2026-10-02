defmodule Controller.ScopeCameraLive do
  @moduledoc """
  The camera in the telescope's focuser, on a phone: focus it by watching
  the stars get small, then tap once and let the telescope find where it's
  pointing (`Controller.AutoAlign`).

  The picture is the latest frame, brightened so faint stars show. Beside it,
  the brightest star up close and the focus number (its half-flux radius:
  smaller is sharper), with the last minute of readings drawn so it's clear
  whether turning the focuser helped. Exposure, gain and stacking are the
  camera's own knobs, with a few presets.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{AutoAlign, ScopeCamera, Settings}


  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      ScopeCamera.subscribe()
      AutoAlign.subscribe()
      Video.subscribe()
      Settings.subscribe()
      send(self(), :rescan)
    end

    {:ok,
     socket
     |> assign(page_title: "Telescope Camera", night: Settings.get("night", false), notice: nil, selected: params["id"] || session["telescope"], refs: %{})
     |> assign(cam: ScopeCamera.find(), playlist: playlist())
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:scope_camera, cam}, socket), do: {:noreply, assign(socket, cam: ScopeCamera.prefer(socket.assigns.cam, cam))}

  def handle_info({:auto_align, id, run}, socket) do
    if id == socket.assigns.selected, do: {:noreply, assign(socket, run: run)}, else: {:noreply, socket}
  end

  def handle_info({:video, v}, socket), do: {:noreply, assign(socket, playlist: v[:playlist])}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()
    assign(socket, refs: refs, selected: selected, run: selected && AutoAlign.status(selected))
  end

  # -- events -------------------------------------------------------------------------------

  @impl true
  def handle_event("live", %{"on" => on}, socket) do
    ScopeCamera.live(on == "true", socket.assigns.cam[:node] || node())
    {:noreply, socket}
  end

  def handle_event("find", _, socket) do
    notice =
      case AutoAlign.start(socket.assigns.selected) do
        :ok -> nil
        {:error, :no_camera} -> "No camera: plug the telescope camera into the box"
        {:error, :no_mount} -> "No mount connected"
        {:error, :running} -> "Already looking"
      end

    {:noreply, socket |> assign(notice: notice) |> rescan()}
  end

  def handle_event("find_continue", _, socket) do
    AutoAlign.continue(socket.assigns.selected)
    {:noreply, rescan(socket)}
  end

  def handle_event("find_stop", _, socket) do
    AutoAlign.stop(socket.assigns.selected)
    {:noreply, rescan(socket)}
  end

  def handle_event("stop", _, socket) do
    if id = socket.assigns.selected do
      AutoAlign.stop(id)
      Controller.Sky.Tracker.stop(id)
      if ref = socket.assigns.refs[id], do: safe(fn -> Mount.stop(ref) end)
    end

    {:noreply, assign(socket, notice: "Stopped")}
  end

  # -- render ----------------------------------------------------------------------------------

  # the newest picture that came out, from the camera's own record of it
  defp newest(cam), do: Enum.find(cam[:frames] || [], &(&1[:ok] != false))

  @impl true
  def render(assigns) do
    assigns = assign(assigns, frame: newest(assigns.cam))

    ~H"""
    <.page id="scope-camera" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="Cameras" />
        <.title>Telescope Camera</.title>
        <.actions><.help href={~p"/docs/scope-camera"} label="the telescope camera" /><.stop /></.actions>
      </:header>

      <p :if={trouble(@cam)} class="hint tone-caution" role="status">{camera_line(@cam)}</p>

      <%!-- the picture takes the room; what to do with it beside (on a phone, below) --%>
      <.split :if={@cam[:camera]}>
        <:main>
          <section :if={@cam[:video]} class="scope-frame" aria-label="live video">
            <video :if={@playlist} id="scope-video" phx-hook="Hls" data-src={"/video/#{@playlist}"} playsinline muted autoplay controls aria-label="live video from the telescope camera"></video>
            <p :if={!@playlist} class="dim">Starting video…</p>
          </section>

          <section :if={!@cam[:video]} class="scope-frame" aria-label="latest picture">
            <img :if={@frame} src={ScopeCamera.src(@cam, @frame.seq)} alt={"Latest picture, frame #{@frame.seq}: #{stars_words(@frame)}"} />
            <div :if={!@frame} class="scope-frame-empty"><p class="dim">No picture yet. Tap Live View.</p></div>
            <p :if={@frame} class="dim" role="status">{caption(@frame, @cam)}</p>
          </section>
        </:main>
        <:side>
          <div class="focus-keys">
            <.btn on={@cam.live} phx-click="live" phx-value-on={to_string(!@cam.live)} disabled={@cam[:video]}>{if @cam.live, do: "Live View On", else: "Live View"}</.btn>
            <.btn navigate={~p"/cameras/telescope/focus"}>Focus</.btn>
          </div>

          <.card title="Find Where It's Pointing">
            <p :if={!@run} class="dim">Moves the mount a few degrees at a time and solves the pictures until four agree.</p>
            <p :if={@run} class={["find-line", @run.done && !@run.ok && "tone-caution"]} role="status">
              <span :if={@run.done && @run.ok} aria-hidden="true">✓ </span>{@run.words}<span :if={!@run.done}> · {@run.solved} of {@run.enough} placed</span>
            </p>
            <.row>
              <.btn :if={!running?(@run)} variant="primary" phx-click="find" disabled={!@selected}>Find Where It's Pointing</.btn>
              <.btn :if={@run && @run[:phase] == :waiting} variant="primary" phx-click="find_continue">Continue</.btn>
              <.btn :if={running?(@run)} phx-click="find_stop">Stop Looking</.btn>
            </.row>
          </.card>

          <%!-- center what's in the picture without leaving it: Nudge, in place --%>
          <.card :if={@selected} title="Move the Scope" class="camera-nudge">
            {live_render(@socket, Controller.NudgeLive, id: "camera-nudge-#{@selected}", session: %{"id" => @selected, "nested" => true})}
          </.card>

          <.items label="more">
            <.link_item navigate={~p"/cameras/telescope/settings"} label="Settings" detail={settings_words(@cam)} />
            <.link_item :if={(@cam[:frames] || []) != []} navigate={~p"/cameras/telescope/frames"} label="Frames" detail={"Last: #{record_title(hd(@cam.frames))}"} />
          </.items>
        </:side>
      </.split>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # only when something's wrong does the camera get a line of its own
  defp trouble(%{camera: nil}), do: true
  defp trouble(%{down: true}), do: true
  defp trouble(%{error: e}) when is_binary(e), do: true
  defp trouble(_), do: false

  # one line under the picture: which, how much light, and whether it has stars
  defp caption(frame, cam) do
    Enum.join(["Frame #{frame.seq}", light(frame), stars_words(frame), cam[:live] && "live"] |> Enum.filter(& &1), " · ")
  end

  defp stars_words(%{stars: 1}), do: "1 star"
  defp stars_words(%{stars: n}) when is_integer(n) and n > 1, do: "#{n} stars"
  defp stars_words(_), do: "no stars"

  # the picture's level in numbers, because a stretched picture can't say how bright it really is
  defp light(%{background: b} = r) when is_number(b) do
    clipped = r[:saturated_pct] || 0
    "background #{round(b)} of 255" <> if(clipped >= 1, do: ", #{round(clipped)}% clipped white", else: "")
  end

  defp light(_), do: nil

  defp settings_words(cam) do
    s = cam[:settings] || %{}
    stack = if (s["stack"] || 1) > 1, do: "#{s["stack"]} stacked", else: "1 frame"
    "#{s["exposure_ms"]} ms, gain #{s["gain"]}, #{stack}#{if cam[:keep], do: ", keeping frames", else: ""}"
  end

  defp camera_line(%{down: true}), do: "The camera part of the box isn't running."
  defp camera_line(%{camera: nil, error: nil}), do: "No camera: plug the telescope camera into the box. It shows up here by itself."
  defp camera_line(%{camera: nil, error: e}), do: e
  defp camera_line(%{error: e}) when is_binary(e), do: e
  defp camera_line(%{camera: name, live: true}), do: "#{name} · live"
  defp camera_line(%{camera: name}), do: name

  # "Frame 123 · live view · 04:14:36 UTC", over what it was asked for and what it found
  defp record_title(r), do: "Frame #{r.seq} · #{r.why} · #{Calendar.strftime(r.at, "%H:%M:%S")} UTC"


  defp playlist do
    Video.status()[:playlist]
  catch
    :exit, _ -> nil
  end

  defp running?(%{done: false}), do: true
  defp running?(_), do: false

  defp safe(fun) do
    fun.()
  catch
    :exit, _ -> nil
  end
end
