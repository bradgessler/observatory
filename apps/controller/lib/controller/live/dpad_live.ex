defmodule Controller.DpadLive do
  @moduledoc """
  The plain keypad: four arrows, a rate row, STOP. Press-and-hold moves the
  named mount axis at the chosen rate; release stops. Kept on the bench as
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
       selected: params["id"] || session["id"],
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

  # -- events -------------------------------------------------------------------------
  # The Stick hook in fixed mode sends "stick" with x/y = the button's direction
  # and mag = 1 while held, every 250 ms; "stick_end" on release.

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
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> socket
            {:error, :limit} -> assign(socket, notice: "soft limit")
            {:error, e} -> assign(socket, notice: inspect(e))
          end
        catch
          :exit, _ -> assign(socket, notice: "mount unreachable")
        end
    end
  end

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, rates: @rates)

    ~H"""
    <.page id="dpad" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/dpad?#{[mount: @selected]}"} label="Bench" />
        <.title>{@selected} · Plain Keypad</.title>
        <.actions><.help href={~p"/docs/keypad"} /></.actions>
      </:header>

      <section class="dpad">
        <span></span>
        <button class={["arrow", :dec in @held && "live"]} id="dp-up" phx-hook="Stick" data-dir="up">▲<small>N · toward pole</small></button>
        <span></span>
        <button class={["arrow", :ra in @held && "live"]} id="dp-left" phx-hook="Stick" data-dir="left">◀<small>E</small></button>
        <%!-- release stops; the always-visible STOP lives in the bench header --%>
        <span class="dpad-centre"><b>{@rate}×</b></span>
        <button class={["arrow", :ra in @held && "live"]} id="dp-right" phx-hook="Stick" data-dir="right">▶<small>W</small></button>
        <span></span>
        <button class={["arrow", :dec in @held && "live"]} id="dp-down" phx-hook="Stick" data-dir="down">▼<small>S · away</small></button>
        <span></span>
      </section>

      <section class="rates">
        <button :for={r <- @rates} class={["rate", r == @rate && "on"]} phx-click="rate" phx-value-rate={r}>{r}×</button>
      </section>

      <.hint>Hold an arrow; it moves at the chosen rate until you let go. E/W turn the polar axis, N/S the Dec axis.</.hint>

      <p :if={@notice} id={"notice-#{:erlang.phash2(@notice)}"} class="notice">{@notice}</p>
    </.page>
    """
  end
end
