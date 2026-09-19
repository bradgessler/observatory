defmodule Controller.MountLive do
  @moduledoc """
  The hand controller. Phone-first: a D-pad you press and hold, a rate picker,
  a big STOP. Talks to whichever mounts the cluster knows about, live.
  """
  use Controller, :live_view

  @rates [1, 8, 64, 400, 800]
  @rescan_ms 3_000

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Controller.Settings.subscribe()
    end

    # `session` carries the mount id when rendered nested inside the bench
    # (nested views get :not_mounted_at_router instead of params)
    params = if(is_map(params), do: params, else: %{}) |> Map.put_new("id", session["id"])
    socket = assign(socket, nested: session["nested"] == true)

    {:ok,
     socket
     |> assign(rate: 64, goto_deg: "5", notice: nil, night: Controller.Settings.get("night", false), more: false, mounts: %{}, refs: %{}, mode: Controller.Settings.get("keypad_mode"), held: [], stick_rate: nil, lat: Controller.Sky.Pointing.site().lat, modes: Controller.Modes.active())
     |> assign(selected: params["id"])
     |> rescan()}
  end

  # No handle_params here on purpose: this view is also rendered nested inside
  # the bench, and child LiveViews may not define it. Mount picks the id.

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
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "keypad_mode", v}, socket), do: {:noreply, assign(socket, mode: v)}
  def handle_info({:settings, _key, _v}, socket),
    do: {:noreply, assign(socket, modes: Controller.Modes.active(), lat: Controller.Sky.Pointing.site().lat)}

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
    if socket.assigns.selected in Map.keys(refs), do: socket, else: assign(socket, selected: first_id(socket))
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Enum.sort() |> List.first()

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
    {:noreply, push_navigate(socket, to: ~p"/#{id}")}
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

  def handle_event("keydown", %{"key" => " "}, socket), do: handle_event("stop", %{}, socket)

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
  def handle_event("estop", _, socket), do: {:noreply, run(socket, &Mount.emergency_stop/1)}
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
        {:noreply, assign(socket, notice: "degrees?")}
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
        assign(socket, notice: "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> assign(socket, notice: nil)
            {:error, :limit} -> assign(socket, notice: "soft limit")
            {:error, :not_connected} -> assign(socket, notice: "mount not connected")
            {:error, other} -> assign(socket, notice: inspect(other))
          end
        catch
          :exit, _ -> assign(socket, notice: "mount unreachable")
        end
    end
  end

  defp current(socket), do: socket.assigns.mounts[socket.assigns.selected]

  # Default is the honest control: one strip per axis of the actual mount.
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
    assigns = assign(assigns, snap: current(%{assigns: assigns}), rates: @rates)

    ~H"""
    <main class={["pad", @night && "night"]} id="pad" phx-window-keydown="keydown" phx-window-keyup="keyup">
      <header :if={!@nested}>
        <form :if={map_size(@refs) > 1} phx-change="select">
          <select name="id">
            <option :for={id <- Enum.sort(Map.keys(@refs))} value={id} selected={id == @selected}>{id}</option>
          </select>
        </form>
        <h1 :if={map_size(@refs) <= 1}>{@selected || "no mount"}</h1>
        <span>
          <.link navigate={if @selected, do: ~p"/sky/#{@selected}", else: ~p"/sky"} class="ghost">✦ sky</.link>
          <.link navigate={~p"/input?#{[mount: @selected]}"} class="ghost" aria-label="game controller">🎮</.link>
          <.link navigate={~p"/devices"} class="ghost" aria-label="devices">⚙</.link>
          <.link href={~p"/docs/keypad"} class="ghost help">?</.link>
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
        </span>
      </header>

      <.link :if={@selected == "sim"} navigate={~p"/devices"} class="banner">No telescope connected — simulator. <strong>Connect ›</strong></.link>

      <%= if @snap && @snap.connected do %>
        <section :if={!@nested} class="readout">
          <div class="axis">
            <span class="label">RA</span>
            <span class="deg">{fmt(@snap.axes.ra.degrees)}</span>
            <span class={["dot", @snap.axes.ra.running && "on"]}></span>
          </div>
          <div class="axis">
            <span class="label">DEC</span>
            <span class="deg">{fmt(@snap.axes.dec.degrees)}</span>
            <span class={["dot", @snap.axes.dec.running && "on"]}></span>
          </div>
          <div class="status">
            <span :if={@snap.tracking != :off} class="badge on">tracking {@snap.tracking}</span>
            <span :if={@snap.tracking == :off} class="badge">not tracking</span>
            <span class={["badge", @snap.homed && "on"]}>{if @snap.homed, do: "homed · limits on", else: "not homed"}</span>
            <span :if={@snap.node != :nonode@nohost} class="badge dim">{@snap.node}</span>
          </div>
        </section>

        <% mode = effective_mode(%{assigns: assigns}) %>
        <%= if mode == :axes do %>
          <section class="eq">
            <%!-- the mount as it stands: polar axis tilted to your latitude, Dec axis square to it --%>
            <svg viewBox="0 0 200 120" class="eq-glyph" aria-hidden="true">
              <% t = -@lat * :math.pi() / 180 %>
              <% {px, py} = {100 + 70 * :math.cos(t), 92 + 70 * :math.sin(t)} %>
              <% {qx, qy} = {100 - 30 * :math.cos(t), 92 - 30 * :math.sin(t)} %>
              <% {dx, dy} = {-:math.sin(t) * 26, :math.cos(t) * 26} %>
              <line x1="10" y1="110" x2="190" y2="110" class="ground" />
              <line x1="100" y1="110" x2="100" y2="92" class="pier" />
              <line x1={qx} y1={qy} x2={px} y2={py} class={["axis", :ra in @held && "live"]} />
              <text x={px - 6} y={py - 6} class="lbl" text-anchor="end">polar axis · {fmt0(@lat)}°</text>
              <line x1={100 - dx} y1={92 - dy} x2={100 + dx} y2={92 + dy} class={["axis", :dec in @held && "live"]} />
              <text x={100 + dx + 4} y={92 + dy + 4} class="lbl">dec</text>
              <text x="14" y="104" class="lbl">S</text>
              <text x="180" y="104" class="lbl">N</text>
            </svg>

            <div class="strip" id="strip-ra" phx-hook="Stick" data-lock="x" data-axis="ra" role="application" aria-label="pull left or right to turn around the polar axis">
              <span class="strip-end">◀ E</span>
              <span class="strip-mid">around the polar axis<b>{if :ra in @held and @stick_rate, do: "#{@stick_rate}×", else: "RA"}</b></span>
              <span class="strip-end">W ▶</span>
              <div class="knob knob-h" data-knob></div>
            </div>

            <div class="strip" id="strip-dec" phx-hook="Stick" data-lock="x" data-axis="dec" role="application" aria-label="pull left or right to turn around the declination axis">
              <span class="strip-end">◀ toward pole</span>
              <span class="strip-mid">around the dec axis<b>{if :dec in @held and @stick_rate, do: "#{@stick_rate}×", else: "Dec"}</b></span>
              <span class="strip-end">away ▶</span>
              <div class="knob knob-h" data-knob></div>
            </div>
          </section>
        <% else %>
          <section class="stick-wrap">
            <div class="stick" id="stick" phx-hook="Stick" role="application" aria-label="touch and pull to move the view">
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
              <div class="knob" data-knob></div>
            </div>
          </section>
        <% end %>
        <div class="stick-foot">
          <button class="ghost" phx-click="mode">{if mode == :sky, do: "blended · moves as you see it (both motors)", else: "one strip per axis"} ▾</button>
          <small :if={mode == :axes and @mode == "sky" and not @snap.homed} class="dim">blended needs home set</small>
        </div>

        <button class="stop-bar" phx-click="estop">STOP</button>

        <section class="row">
          <button :if={@snap.tracking == :off} phx-click="track" phx-value-mode="sidereal">Track ☆</button>
          <button :if={@snap.tracking != :off} class="on" phx-click="track" phx-value-mode="off">Tracking ☆</button>
          <.link navigate={~p"/setup/#{@selected}"} class="btn-link">Setup ›</.link>
        </section>

        <Controller.Components.Modes.modes modes={@modes} id={@selected} />
      <% else %>
        <section class="empty">
          <p :if={@snap}>{@selected}: not connected<span :if={@snap[:error]}> — {inspect(@snap.error)}</span></p>
          <p :if={!@snap}>No mount found. Plug the EQDIR cable into this machine, or connect to a node that has one.</p>
        </section>
      <% end %>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </main>
    """
  end

  defp fmt(deg) when is_number(deg) do
    sign = if deg < 0, do: "−", else: "+"
    d = abs(deg)
    whole = trunc(d)
    min = (d - whole) * 60
    "#{sign}#{whole}° #{:erlang.float_to_binary(min * 1.0, decimals: 1)}′"
  end

  defp fmt(_), do: "—"

  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)
end
