defmodule Controller.BenchLive do
  @moduledoc """
  The bench: the front door while we're playing with components. One
  telescope, several devices, several control surfaces. The header shows the
  live state of every device (mount, pad, camera); the nav picks a surface;
  the surface renders below as a nested LiveView. Not the field UI.
  """
  use Controller, :live_view
  import Controller.Components.Status

  alias Controller.Settings

  @surfaces [
    {"strips", "Axis Strips", Controller.MountLive, "one pull-to-speed strip per mount axis; the field keypad"},
    {"lineup", "Line Up", Controller.LineupLive, "name a few stars; the software works out how the mount sits"},
    {"dpad", "Plain Keypad", Controller.DpadLive, "four arrows and a rate row; the boring one"},
    {"nudge", "Nudge", Controller.NudgeLive, "tap to move an exact step: 1′, 5′, 30′, 2°; for centering"},
    {"orb", "Orb", Controller.OrbLive, "the equatorial geometry as a 3-D gizmo, with analog strips"},
    {"tilt", "Tilt", Controller.TiltLive, "eyepiece mode: hold the button, tilt the phone"},
    {"position", "Position", Controller.PositionLive, "set an axis angle, go home; the put-it-back tool"},
    {"gamepad", "Game Controller", Controller.InputLive, "a USB pad read by the server"},
    {"watch", "Watch", Controller.WatchLive, "a camera on the mount, read by the server"},
    {"sky", "Sky", Controller.SkyLive, "map, tonight's targets, horizon"}
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
    {:noreply, assign(socket, surface: surface, selected: params["mount"] || socket.assigns.selected)}
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
        <span class="hdr-actions">
          <%!-- one STOP, always visible, whatever surface is up --%>
          <button class="stop-mini" phx-click="estop" aria-label="stop the mount">STOP</button>
          <.link navigate={~p"/devices"} class="ghost" aria-label="devices">⚙</.link>
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
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
        <.link :for={{key, name, _mod, blurb} <- @surfaces} patch={~p"/bench/#{key}?#{[mount: @selected]}"} class={["bench-tab", key == @surface && "on"]}>
          <strong>{name}</strong><span>{blurb}</span>
        </.link>
      </nav>

      <section class="bench-stage">
        <%= if @current do %>
          <% {key, _name, mod, _} = @current %>
          <%= live_render(@socket, mod, id: "surface-#{key}-#{@selected}", session: %{"id" => @selected, "mount" => @selected, "nested" => true}) %>
        <% end %>
      </section>
    </main>
    """
  end
end
