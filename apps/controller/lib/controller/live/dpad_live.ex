defmodule Controller.DpadLive do
  @moduledoc """
  The plain keypad: four arrows, a rate row, STOP. Press-and-hold moves the
  named mount axis at the chosen rate; release stops. Kept in Controls as
  the baseline everything else is measured against.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @rates [1, 8, 64, 400, 800]

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
    end

    # nested views get :not_mounted_at_router instead of params
    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       refs: %{},
       selected: params["id"] || session["id"] || session["telescope"],
       snap: nil,
       rate: 64,
       held: [],
       notice: nil
     )
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    assign(socket, refs: refs, selected: selected, snap: snap, page_title: Controller.Words.title(selected, "Plain Keypad"))
  end

  # -- events -------------------------------------------------------------------------
  # The Stick hook in fixed mode sends "stick" with x/y = the button's direction
  # and mag = 1 while held, every 250 ms; "stick_end" on release. The arrow
  # keys send the same: key auto-repeat feeds the deadman, keyup lets go.
  @arrows %{"ArrowUp" => {0, 1}, "ArrowDown" => {0, -1}, "ArrowLeft" => {-1, 0}, "ArrowRight" => {1, 0}}

  @impl true
  def handle_event("rate", %{"rate" => r}, socket), do: {:noreply, assign(socket, rate: String.to_integer(r))}

  def handle_event("stick", %{"x" => x, "y" => y}, socket) do
    ctx = Controller.Sky.Pointing.context()
    rates = Controller.Sky.Joystick.compass_vector(socket.assigns.snap, ctx, {x / 1, y / 1}, socket.assigns.rate / 1)
    socket = Enum.reduce(rates, socket, fn {axis, r}, s -> run(s, &Mount.slew(&1, axis, r, hold: true)) end)
    {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)))}
  end

  def handle_event("stick_end", _, socket) do
    snap = socket.assigns.snap

    socket =
      Enum.reduce(socket.assigns.held, socket, fn axis, s ->
        if axis == :ra and snap && snap.tracking != :off,
          do: run(s, &Mount.track(&1, snap.tracking)),
          else: run(s, &Mount.stop(&1, axis))
      end)

    {:noreply, assign(socket, held: [])}
  end

  def handle_event("estop", _, socket) do
    Controller.Sky.Tracker.stop_all()
    {:noreply, run(socket, &Mount.emergency_stop/1)}
  end

  def handle_event("keydown", %{"key" => k}, socket) when k in [" ", "Escape"], do: handle_event("estop", %{}, socket)

  def handle_event("keydown", %{"key" => key}, socket) when is_map_key(@arrows, key) do
    {x, y} = @arrows[key]
    handle_event("stick", %{"x" => x, "y" => y, "mag" => 1}, socket)
  end

  def handle_event("keyup", %{"key" => key}, socket) when is_map_key(@arrows, key), do: handle_event("stick_end", %{}, socket)
  def handle_event(k, _params, socket) when k in ["keydown", "keyup"], do: {:noreply, socket}
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "No mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> socket
            {:error, :limit} -> assign(socket, notice: "Soft limit")
            {:error, e} -> assign(socket, notice: Controller.Words.error(e))
          end
        catch
          :exit, _ -> assign(socket, notice: "Mount unreachable")
        end
    end
  end

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, rates: @rates)

    ~H"""
    <.page id="dpad" night={@night} class={@nested && "nested"} phx-window-keydown="keydown" phx-window-keyup="keyup">
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Controls", @selected)} />
        <.title>Plain Keypad</.title>
        <.actions><.help href={~p"/docs/keypad"} label="the keypad" /><.stop click="estop" /></.actions>
      </:header>

      <%!-- hold to move, release to stop: the dead-man is the point (2.5.2); arrow keys are the same controls --%>
      <section class="dpad" role="group" aria-label="hold to move" aria-describedby="dpad-how">
        <span></span>
        <button class={["arrow", :dec in @held && "live"]} id="dp-up" phx-hook="Stick" data-dir="up" aria-label="move north, toward the pole" aria-pressed={to_string(:dec in @held)}><span aria-hidden="true">▲</span><small>N · toward pole</small></button>
        <span></span>
        <button class={["arrow", :ra in @held && "live"]} id="dp-left" phx-hook="Stick" data-dir="left" aria-label="move east" aria-pressed={to_string(:ra in @held)}><span aria-hidden="true">◀</span><small>E</small></button>
        <%!-- release stops; the always-visible STOP lives in the header --%>
        <span class="dpad-centre" aria-live="off"><b>{@rate}×</b></span>
        <button class={["arrow", :ra in @held && "live"]} id="dp-right" phx-hook="Stick" data-dir="right" aria-label="move west" aria-pressed={to_string(:ra in @held)}><span aria-hidden="true">▶</span><small>W</small></button>
        <span></span>
        <button class={["arrow", :dec in @held && "live"]} id="dp-down" phx-hook="Stick" data-dir="down" aria-label="move south, away from the pole" aria-pressed={to_string(:dec in @held)}><span aria-hidden="true">▼</span><small>S · away</small></button>
        <span></span>
      </section>

      <.rates label="slew rate">
        <:opt :for={r <- @rates} on={r == @rate} click="rate" value={%{rate: r}}>{r}×</:opt>
      </.rates>

      <.hint id="dpad-how">Hold an arrow; it moves at the chosen rate until you let go. E/W turn the RA axis, N/S the Dec axis. On a keyboard the arrow keys do the same; space or Escape stops.</.hint>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
