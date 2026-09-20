defmodule Controller.BenchLive do
  @moduledoc """
  The bench: the front door while we're playing with components. One
  telescope, several devices, several control surfaces. The header shows the
  live state of every device (mount, pad, camera); the nav picks a surface;
  the surface renders below as a nested LiveView. Not the field UI.
  """
  use Controller, :live_view
  import Controller.Components.UI
  import Controller.Components.Status

  alias Controller.Settings

  @surfaces [
    {"strips", "Axis Strips", Controller.MountLive, "One pull-to-speed strip per axis; the field keypad"},
    {"align", "Star Align", Controller.LineupLive, "Name a few stars; the software works out how the mount really sits"},
    {"dpad", "Plain Keypad", Controller.DpadLive, "Four arrows and a rate row; the baseline"},
    {"nudge", "Nudge", Controller.NudgeLive, "Tap to move an exact 1′, 5′, 30′ or 2°; for centring"},
    {"eyepiece", "Eyepiece", Controller.EyepieceLive, "What the tube sees: the field, the target, the drift"},
    {"scope", "Scope", Controller.ScopeLive, "The mount as a picture, posed from the encoders"},
    {"orb", "Orb", Controller.OrbLive, "The mount's geometry as a 3-D gizmo, live, with strips to turn each axis"},
    {"tilt", "Tilt", Controller.TiltLive, "Hold the button, tilt the phone; for when your eye is on the eyepiece"},
    {"position", "Position", Controller.PositionLive, "Type an axis angle, go there; go home"},
    {"gamepad", "Game Controller", Controller.InputLive, "A USB pad read by the server: trigger is the dead-man, the ball is speed"},
    {"watch", "Watch", Controller.WatchLive, "The latest still, kept fresh; press Play for live video"},
    {"sky", "Sky", Controller.SkyLive, "The sky right now, tonight's targets, your tree line; tap and slew"}
  ]

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Input.subscribe()
      Watch.subscribe()
    end

    {:ok,
     socket
     |> assign(night: Settings.get("night", false), refs: %{}, selected: params["mount"], snap: nil, surface: nil, modes: Controller.Modes.active())
     |> assign(pad: Input.status(), pads: Input.devices(), camera: Watch.status())
     |> rescan()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    surface = if Enum.any?(@surfaces, fn {k, _, _, _} -> k == params["surface"] end), do: params["surface"], else: "strips"
    {_, name, _, _} = Enum.find(@surfaces, fn {k, _, _, _} -> k == surface end)
    {:noreply, assign(socket, surface: surface, page_title: "Bench · #{name}", selected: params["mount"] || socket.assigns.selected)}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> assign(pads: Input.devices(), camera: Watch.status())}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:mapper, status}, socket), do: {:noreply, assign(socket, pad: status)}
  def handle_info({:input, _id, _info}, socket), do: {:noreply, socket}
  def handle_info({:input_gone, _id}, socket), do: {:noreply, assign(socket, pads: Input.devices())}
  def handle_info({:watch, _meta}, socket), do: {:noreply, assign(socket, camera: Watch.status())}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v, modes: Controller.Modes.active())}
  def handle_info({:settings, _, _}, socket), do: {:noreply, assign(socket, modes: Controller.Modes.active())}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    assign(socket, refs: refs, selected: selected, snap: snap)
  end

  @impl true
  def handle_event("estop", _, socket) do
    if ref = socket.assigns.refs[socket.assigns.selected] do
      try do
        Mount.emergency_stop(ref)
      catch
        :exit, _ -> :ok
      end
    end

    Input.arm(false)
    Controller.Sky.Tracker.stop_all()
    # a scan in progress ends where it stands: after a STOP nothing moves the mount
    try do
      Controller.Optical.AxisScan.cancel(return: false)
    catch
      :exit, _ -> :ok
    end

    {:noreply, socket}
  end

  def handle_event("night", _, socket) do
    v = !socket.assigns.night
    Settings.put("night", v)
    {:noreply, assign(socket, night: v)}
  end

  @impl true
  def render(assigns) do
    assigns = assign(assigns, surfaces: @surfaces, current: Enum.find(@surfaces, fn {k, _, _, _} -> k == assigns.surface end))

    ~H"""
    <main class={["bench", @night && "night"]} id="bench">
      <header class="bench-head">
        <.link navigate={~p"/"} class="bench-brand">‹ Bench</.link>
        <h1 class="sr-only">Bench · {if @current, do: elem(@current, 1), else: "no surface"}</h1>
        <span class="hdr-actions">
          <%!-- one STOP, always visible, whatever surface is up --%>
          <.stop click="estop" />
          <.link navigate={~p"/devices"} class="ghost" aria-label="devices">⚙</.link>
          <button class="ghost" phx-click="night" aria-label="night mode" aria-pressed={to_string(@night)}>◐</button>
        </span>
        <div class="bench-devices">
          <.status snap={@snap} id={@selected} compact />
          <%!-- modes are loud, but once: one amber chip here instead of a banner on every surface --%>
          <.link :if={@modes != [] and @selected} navigate={~p"/setup/#{@selected}"} class="dev-chip mode-chip" title={Enum.map_join(@modes, " · ", fn {l, d} -> "#{l} #{d}" end)}>
            <b>modes</b><span class="ss-badge warn">{length(@modes)} on</span>
          </.link>
          <.link patch={~p"/bench/gamepad?#{[mount: @selected]}"} class="dev-chip">
            <b>pad</b>
            <span :if={@pads == []} class="ss-badge warn">none</span>
            <span :if={@pads != [] and !@pad.armed} class="ss-badge">watch only</span>
            <span :if={@pads != [] and @pad.armed} class={["ss-badge", "on"]}>{if @pad.held == [], do: "live", else: "moving"}</span>
          </.link>
          <.link patch={~p"/bench/watch?#{[mount: @selected]}"} class="dev-chip">
            <b>camera</b>
            <span :if={is_nil(@camera.tool)} class="ss-badge warn">none</span>
            <span :if={@camera.tool && !@camera.enabled} class="ss-badge">{if @camera.latest, do: "frame #{@camera.frames}", else: "idle"}</span>
            <span :if={@camera.tool && @camera.enabled} class="ss-badge on">live</span>
          </.link>
        </div>
      </header>

      <nav class="bench-nav" aria-label="control surfaces">
        <.link :for={{key, name, _mod, blurb} <- @surfaces} patch={~p"/bench/#{key}?#{[mount: @selected]}"} class={["bench-tab", key == @surface && "on"]} aria-current={if key == @surface, do: "page"}>
          <strong>{name}</strong><span>{blurb}</span>
        </.link>
      </nav>

      <.skip_target />
      <section class="bench-stage" aria-label={if @current, do: elem(@current, 1)}>
        <%= if @current do %>
          <% {key, _name, mod, _} = @current %>
          <%= live_render(@socket, mod, id: "surface-#{key}-#{@selected}", session: %{"id" => @selected, "mount" => @selected, "nested" => true}) %>
        <% end %>
      </section>
    </main>
    """
  end
end
