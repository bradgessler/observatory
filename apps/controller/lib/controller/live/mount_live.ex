defmodule Controller.MountLive do
  @moduledoc """
  The hand controller. Phone-first: a D-pad you press and hold, a rate picker,
  a big STOP. Talks to whichever mounts the cluster knows about, live.
  """
  use Controller, :live_view
  import Controller.Components.UI

  @rates [1, 8, 64, 400, 800]
  @rescan_ms 3_000

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Controller.Settings.subscribe()
      # the viewfinder: what the telescope camera sees, beside the strips
      Controller.ScopeCamera.subscribe()
    end

    # `session` carries the mount id when rendered nested inside another page
    # (nested views get :not_mounted_at_router instead of params)
    params = if(is_map(params), do: params, else: %{}) |> Map.put_new("id", session["id"])
    socket = assign(socket, nested: session["nested"] == true)

    {:ok,
     socket
     |> assign(rate: 64, goto_deg: "5", notice: nil, night: Controller.Settings.get("night", false), more: false, mounts: %{}, refs: %{}, mode: Controller.Settings.get("keypad_mode"), held: [], stick_rate: nil, modes: Controller.Modes.active(), cam: Controller.ScopeCamera.find())
     |> assign(selected: params["id"] || session["telescope"])
     |> rescan()}
  end

  # No handle_params here on purpose: this view can be rendered nested inside
  # another page, and child LiveViews may not define it. Mount picks the id.

  # -- live updates -------------------------------------------------------------

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, @rescan_ms)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    {:noreply, assign(socket, mounts: Map.put(socket.assigns.mounts, snap.id, snap))}
  end

  # A setting changed on some phone: pick up the ones this page shows.
  def handle_info({:scope_camera, heard}, socket), do: {:noreply, assign(socket, cam: Controller.ScopeCamera.prefer(socket.assigns.cam, heard))}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "keypad_mode", v}, socket), do: {:noreply, assign(socket, mode: v)}
  def handle_info({:settings, _key, _v}, socket),
    do: {:noreply, assign(socket, modes: Controller.Modes.active())}
  def handle_info(_, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})

    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id) do
      Mount.subscribe(ref)
    end

    mounts =
      for {id, ref} <- refs, into: %{} do
        {id, socket.assigns.mounts[id] || safe_snapshot(ref)}
      end

    socket = assign(socket, refs: refs, mounts: mounts)
    socket = if socket.assigns.selected in Map.keys(refs), do: socket, else: assign(socket, selected: first_id(socket))
    assign(socket, page_title: Controller.Words.title(socket.assigns.selected, "Axis Strips"))
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Mount.default()

  defp safe_snapshot(ref) do
    try do
      Mount.snapshot(ref)
    catch
      _, _ -> %{id: ref.id, node: ref.node, connected: false, axes: %{}, tracking: :off, homed: false}
    end
  end

  # -- events -----------------------------------------------------------------------

  @impl true
  def handle_event("select", %{"id" => id}, socket) do
    {:noreply, push_navigate(socket, to: ~p"/keypad/#{id}")}
  end

  def handle_event("rate", %{"rate" => r}, socket) do
    {:noreply, assign(socket, rate: String.to_integer(r))}
  end

  # The arrows mean a direction on the sky, not an axis. In sky mode "up" is
  # toward the zenith and both axes may turn; in axes mode it's the
  # hand-controller convention (N/S = Dec, E/W = RA).
  def handle_event("hold", %{"dir" => dir}, socket) when dir in ~w(up down left right) do
    dir = String.to_existing_atom(dir)
    snap = current(socket)
    ctx = Controller.Sky.Pointing.context()

    rates =
      case effective_mode(socket) do
        :sky -> Controller.Sky.Joystick.sky(snap, ctx, dir, socket.assigns.rate)
        :axes -> Controller.Sky.Joystick.compass(snap, ctx, dir, socket.assigns.rate)
      end || Controller.Sky.Joystick.compass(snap, ctx, dir, socket.assigns.rate)

    socket = Enum.reduce(rates, socket, fn {axis, rate}, s -> run(s, &Mount.slew(&1, axis, rate, hold: true)) end)
    {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)))}
  end

  def handle_event("release", _params, socket) do
    snap = current(socket)
    held = socket.assigns[:held] || [:ra, :dec]

    socket =
      Enum.reduce(held, socket, fn axis, s ->
        # Letting go of an RA nudge while tracking should go back to tracking, not stop.
        if axis == :ra and snap && snap.tracking != :off,
          do: run(s, &Mount.track(&1, snap.tracking)),
          else: run(s, &Mount.stop(&1, axis))
      end)

    {:noreply, assign(socket, held: [])}
  end

  # Laptop keyboard via phx-window-keydown/keyup (no JS). Key auto-repeat keeps
  # sending keydown, which keeps refreshing the mount's hold deadman.
  @arrows %{"ArrowUp" => "up", "ArrowDown" => "down", "ArrowLeft" => "left", "ArrowRight" => "right"}

  # space and Escape both stop: Escape is not a character key (2.1.4), space is
  # the big one a startled hand finds; an accidental stop is harmless
  def handle_event("keydown", %{"key" => k}, socket) when k in [" ", "Escape"], do: handle_event("stop", %{}, socket)

  def handle_event("keydown", %{"key" => key}, socket) when is_map_key(@arrows, key),
    do: handle_event("hold", %{"dir" => @arrows[key]}, socket)

  def handle_event("keyup", %{"key" => key}, socket) when is_map_key(@arrows, key),
    do: handle_event("release", %{}, socket)

  def handle_event(k, _params, socket) when k in ["keydown", "keyup"], do: {:noreply, socket}

  # The stick: touch and pull. Direction is where you pulled (as you see it, or
  # N/S/E/W in axes mode); speed grows with distance on a log scale from 1× at
  # the dead zone to 800× at the rim. The hook re-sends while held, which keeps
  # the mount's deadman fed; letting go sends stick_end.
  @stick_max 800.0

  def handle_event("stick", %{"x" => x, "y" => y, "mag" => mag} = params, socket)
      when is_number(x) and is_number(y) and is_number(mag) do
    mag = mag |> max(0.0) |> min(1.0)
    rate = :math.pow(@stick_max, mag) |> max(1.0)
    snap = current(socket)
    ctx = Controller.Sky.Pointing.context()

    # A per-axis strip is horizontal: its pull is one axis only, never a blend.
    vector =
      case params["axis"] do
        "ra" -> {x / 1, 0.0}
        "dec" -> {0.0, x / 1}
        _ -> {x / 1, y / 1}
      end

    rates =
      case {effective_mode(socket), params["axis"]} do
        {:sky, nil} -> Controller.Sky.Joystick.sky_vector(snap, ctx, vector, rate)
        _ -> Controller.Sky.Joystick.compass_vector(snap, ctx, vector, rate)
      end || Controller.Sky.Joystick.compass_vector(snap, ctx, vector, rate)

    socket = Enum.reduce(rates, socket, fn {axis, r}, s -> run(s, &Mount.slew(&1, axis, r, hold: true)) end)
    {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)), stick_rate: round(rate))}
  end

  def handle_event("stick_end", _params, socket) do
    {:noreply, socket} = handle_event("release", %{}, socket)
    {:noreply, assign(socket, stick_rate: nil)}
  end

  def handle_event("mode", _, socket) do
    mode = if effective_mode(socket) == :sky, do: "axes", else: "sky"
    Controller.Settings.put("keypad_mode", mode)
    {:noreply, assign(socket, mode: mode)}
  end

  def handle_event("stop", _, socket), do: {:noreply, run(socket, &Mount.stop/1)}
  def handle_event("estop", _, socket) do
    Controller.Sky.Tracker.stop_all()
    {:noreply, run(socket, &Mount.emergency_stop/1)}
  end
  def handle_event("home", _, socket), do: {:noreply, run(socket, &Mount.set_home/1)}

  def handle_event("track", %{"mode" => mode}, socket) do
    {:noreply, run(socket, &Mount.track(&1, String.to_existing_atom(mode)))}
  end

  def handle_event("goto", %{"axis" => axis, "sign" => sign, "deg" => deg}, socket) do
    case Float.parse(deg) do
      {d, _} ->
        d = if sign == "-", do: -d, else: d
        {:noreply, socket |> assign(goto_deg: deg) |> run(&Mount.goto_relative(&1, String.to_existing_atom(axis), d))}

      :error ->
        {:noreply, assign(socket, notice: "Degrees?")}
    end
  end

  def handle_event("night", _, socket) do
    night = !socket.assigns.night
    Controller.Settings.put("night", night)
    {:noreply, assign(socket, night: night)}
  end
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}
  def handle_event("more", _, socket), do: {:noreply, assign(socket, more: !socket.assigns.more)}

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "No mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> assign(socket, notice: nil)
            {:error, :limit} -> assign(socket, notice: "Soft limit")
            {:error, :not_connected} -> assign(socket, notice: "Mount not connected")
            {:error, other} -> assign(socket, notice: Controller.Words.error(other))
          end
        catch
          :exit, _ -> assign(socket, notice: "Mount unreachable")
        end
    end
  end

  # the mount drawn as it stands: from the snapshot, the site and the alignment, like the Scope page
  defp pose_of(%{connected: true} = snap, id) do
    Controller.Components.Scope.pose_from(snap, Controller.Sky.Pointing.context(DateTime.utc_now(), id))
  rescue
    _ -> nil
  end

  defp pose_of(_, _), do: nil

  defp current(socket), do: socket.assigns.mounts[socket.assigns.selected]

  # Default is the honest control: One strip per axis of the actual mount.
  # "Blended" (move as you see it, both motors at once) is opt-in and needs home.
  defp effective_mode(socket) do
    snap = current(socket)
    homed? = snap != nil and snap[:homed] == true

    case socket.assigns[:mode] do
      "sky" when homed? -> :sky
      _ -> :axes
    end
  end

  # -- render -----------------------------------------------------------------------

  @impl true
  def render(assigns) do
    snap = current(%{assigns: assigns})
    assigns = assign(assigns, snap: snap, rates: @rates, pose: pose_of(snap, assigns.selected))

    ~H"""
    <%!-- one <main> per document: nested inside another page this is a plain block --%>
    <.dynamic_tag tag_name={if @nested, do: "div", else: "main"} class={["pad", @night && "night"]} id="pad" phx-window-keydown="keydown" phx-window-keyup="keyup">
      <header :if={!@nested} class="page-header">
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Controls", @selected)} />
        <.title>Axis Strips</.title>
        <%!-- the Controls section's status: what the mount is doing and where it points --%>
        <.status label="Mount">{live_render(@socket, Controller.ControlsStatusLive, id: "controls-status", session: %{"id" => @selected})}</.status>
        <.actions>
          <.help href={~p"/docs/keypad"} label="the keypad" />
          <.stop click="estop" />
        </.actions>
      </header>
      <%!-- more than one mount: which one these strips drive --%>
      <div :if={!@nested and map_size(@refs) > 1} class="mount-pick">
        <form phx-change="select">
          <%!-- picking another mount opens its keypad: the name says so before you change it (3.2.2) --%>
          <label for="mount-pick-id">Mount</label>
          <select id="mount-pick-id" name="id" aria-label="switch to another mount's keypad">
            <option :for={id <- Enum.sort(Map.keys(@refs))} value={id} selected={id == @selected}>{id}</option>
          </select>
        </form>
      </div>
      <.skip_target :if={!@nested} />

      <.link :if={Mount.simulated?(@selected)} navigate={~p"/devices"} class="hint sim-line">Simulator · no telescope on the cable · Devices ›</.link>

      <%= if @snap && @snap.connected do %>
        <% mode = effective_mode(%{assigns: assigns}) %>
        <%!-- the mount and where it points take the room; the strips, STOP and tracking beside them (on a phone, below) --%>
        <.split class="pad-split">
          <:main>
            <section :if={!@nested} class="readout">
              <div class="axis">
                <span class="label">RA</span>
                <span class="deg">{fmt(@snap.axes.ra.degrees)}</span>
                <.lamp on={@snap.axes.ra.running} />
              </div>
              <div class="axis">
                <span class="label">DEC</span>
                <span class="deg">{fmt(@snap.axes.dec.degrees)}</span>
                <.lamp on={@snap.axes.dec.running} />
              </div>
              <div class="status">
                <span :if={@snap.tracking != :off} class="badge on">tracking {@snap.tracking}</span>
                <span :if={@snap.tracking == :off} class="badge">not tracking</span>
                <span class={["badge", @snap.homed && "on"]}>{if @snap.homed, do: "homed · limits on", else: "not homed"}</span>
                <span :if={@snap.node != :nonode@nohost} class="badge dim">{Controller.Words.host(@snap.node)}</span>
              </div>
            </section>
            <%!-- what the telescope sees, when it has a camera: drive and look in one place --%>
            <Controller.Components.Viewfinder.viewfinder cam={@cam} />
            <%!-- the mount as it stands, posed from the encoders, in 3-D (Render3D, on the server) --%>
            <Controller.Components.Scope.scope :if={@pose} pose={@pose} size={360} label={@selected} class="pad-scope" />
          </:main>
          <:side>
            <%= if mode == :axes do %>
              <section class="eq">

                <div class="strip" id="strip-ra" phx-hook="Stick" data-lock="x" data-axis="ra" role="group" aria-label="pull left or right to turn around the polar axis" aria-describedby="pad-how">
                  <span class="strip-end"><span aria-hidden="true">◀ </span>E</span>
                  <span class="strip-mid">around the polar axis<b>{if :ra in @held and @stick_rate, do: "#{@stick_rate}×", else: "RA"}</b></span>
                  <span class="strip-end">W<span aria-hidden="true"> ▶</span></span>
                  <div class="knob knob-h" data-knob aria-hidden="true"></div>
                </div>

                <div class="strip" id="strip-dec" phx-hook="Stick" data-lock="x" data-axis="dec" role="group" aria-label="pull left or right to turn around the declination axis" aria-describedby="pad-how">
                  <span class="strip-end"><span aria-hidden="true">◀ </span>toward pole</span>
                  <span class="strip-mid">around the dec axis<b>{if :dec in @held and @stick_rate, do: "#{@stick_rate}×", else: "Dec"}</b></span>
                  <span class="strip-end">away<span aria-hidden="true"> ▶</span></span>
                  <div class="knob knob-h" data-knob aria-hidden="true"></div>
                </div>
              </section>
            <% else %>
              <section class="stick-wrap">
                <div class="stick" id="stick" phx-hook="Stick" role="group" aria-label="touch and pull to move the view" aria-describedby="pad-how">
                  <svg viewBox="-100 -100 200 200" class="stick-face" aria-hidden="true">
                    <circle r="98" class="rim" />
                    <circle r="62" class="ring" />
                    <circle r="28" class="ring" />
                    <circle r="12" class="dead" />
                    <text x="0" y="-80" class="lbl">up</text>
                    <text x="0" y="90" class="lbl">down</text>
                    <text x="-84" y="4" class="lbl">left</text>
                    <text x="84" y="4" class="lbl">right</text>
                    <text x="0" y="6" class="rate-lbl">{if @stick_rate, do: "#{@stick_rate}×", else: ""}</text>
                  </svg>
                  <div class="knob" data-knob aria-hidden="true"></div>
                </div>
              </section>
            <% end %>
            <div class="stick-foot">
              <button class="ghost" phx-click="mode" aria-label={"strip layout: #{if mode == :sky, do: "blended, moves as you see it", else: "One strip per axis"}; switch"}>{if mode == :sky, do: "blended · moves as you see it (both motors)", else: "One strip per axis"} <span aria-hidden="true">▾</span></button>
              <small :if={mode == :axes and @mode == "sky" and not @snap.homed} class="dim">blended needs home set</small>
            </div>
            <%!-- the strips are a pull gesture and the motion stops when you let go, by design (2.5.1, 2.5.2); the keyboard is the one-key path --%>
            <.hint id="pad-how">Pull to turn; letting go stops. On a keyboard the arrow keys do the same and space or Escape stops.</.hint>

            <.stop :if={!@nested} size="bar" click="estop" />

            <section class="row">
              <button :if={@snap.tracking == :off} phx-click="track" phx-value-mode="sidereal" aria-pressed="false">Track <span aria-hidden="true">☆</span></button>
              <button :if={@snap.tracking != :off} class="on" phx-click="track" phx-value-mode="off" aria-pressed="true">Tracking <span aria-hidden="true">☆</span></button>
              <.link navigate={~p"/setup/#{@selected}"} class="btn-link">Setup ›</.link>
            </section>

            <Controller.Components.Modes.modes :if={!@nested} modes={@modes} id={@selected} />
          </:side>
        </.split>
      <% else %>
        <section class="empty">
          <p :if={@snap}>{@selected} isn't answering<span :if={@snap[:error]}>: {Controller.Words.mount_problem(@snap.error)}</span></p>
          <p :if={!@snap}>No mount found. Plug the EQDIR cable into this machine or a box; it's found by itself.</p>
          <.row><.btn navigate={if @snap, do: ~p"/devices/mount/#{@selected}", else: ~p"/devices"}>{if @snap, do: "#{@selected} on Devices ›", else: "Devices ›"}</.btn></.row>
        </section>
        <%!-- STOP is on every page, answering or not: a link lost mid-slew is when it matters --%>
        <.stop :if={!@nested} size="bar" click="estop" />
      <% end %>

      <.notice notice={@notice} />
    </.dynamic_tag>
    """
  end

  defp fmt(deg) when is_number(deg) do
    sign = if deg < 0, do: "−", else: "+"
    d = abs(deg)
    whole = trunc(d)
    min = (d - whole) * 60
    "#{sign}#{whole}° #{:erlang.float_to_binary(min * 1.0, decimals: 1)}′"
  end

  defp fmt(_), do: Controller.Words.none()

end
