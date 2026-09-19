defmodule Controller.InputLive do
  @moduledoc """
  Hardware inputs. A gamepad plugged into the machine showing this page is
  read by the browser (macOS/Windows have no device file to read from Elixir)
  and its state is sent here ~20×/s while something is pressed. The mapping
  to mount motion is server-side and pure (`Controller.Input.Gamepad`), so a
  Pi reading the same pad over evdev drives the mount identically.

  Shows the raw axes/buttons so an unknown pad can be mapped by looking.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Input.Gamepad
  alias Controller.Settings

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
    end

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       refs: %{},
       selected: params["mount"],
       snap: nil,
       pads: [],
       state: nil,
       action: :idle,
       held: [],
       start: nil,
       notice: nil,
       armed: true
     )
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
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
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end) |> ok_or_nil()
    assign(socket, refs: refs, selected: selected, snap: snap)
  end

  # -- events from the hook ---------------------------------------------------------

  @impl true
  def handle_event("pads", %{"pads" => pads}, socket), do: {:noreply, assign(socket, pads: pads)}

  def handle_event("gamepad", %{"axes" => axes, "buttons" => buttons} = st, socket) do
    state = %{axes: axes, buttons: buttons, hat: hat_from(st["hat"])}
    action = Gamepad.interpret(state)
    ref = socket.assigns.refs[socket.assigns.selected]
    socket = assign(socket, state: state, action: action)

    cond do
      is_nil(ref) or not socket.assigns.armed ->
        {:noreply, socket}

      action == :stop ->
        safe(fn -> Mount.emergency_stop(ref) end)
        {:noreply, assign(socket, held: [], start: nil, notice: "STOP from the pad")}

      match?({_, _}, action) ->
        {_, rates} = action
        for {axis, r} <- rates, do: safe(fn -> Mount.slew(ref, axis, r, hold: true) end)
        start = socket.assigns.start || (socket.assigns.snap && {socket.assigns.snap.axes.ra.degrees, socket.assigns.snap.axes.dec.degrees})
        {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)), start: start)}

      true ->
        {:noreply, release(socket)}
    end
  end

  def handle_event("gamepad_idle", _, socket), do: {:noreply, release(socket)}

  def handle_event("arm", _, socket), do: {:noreply, assign(socket, armed: !socket.assigns.armed)}
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp release(%{assigns: %{held: []}} = socket), do: socket

  defp release(socket) do
    ref = socket.assigns.refs[socket.assigns.selected]
    snap = socket.assigns.snap

    for axis <- socket.assigns.held do
      if axis == :ra and snap && snap.tracking != :off,
        do: safe(fn -> Mount.track(ref, snap.tracking) end),
        else: safe(fn -> Mount.stop(ref, axis) end)
    end

    assign(socket, held: [])
  end

  defp hat_from([x, y]) when is_number(x) and is_number(y), do: {round(x), round(y)}
  defp hat_from(_), do: nil

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end

  defp ok_or_nil({:error, _}), do: nil
  defp ok_or_nil(v), do: v

  # -- render -----------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="input" night={@night} phx-hook="Gamepad">
      <:header>
        <.back navigate={if @selected, do: ~p"/#{@selected}", else: ~p"/"} label="keypad" />
        <.title>controller</.title>
        <.actions><.btn variant="danger" phx-click="arm" on={!@armed}>{if @armed, do: "Disarm", else: "Armed off"}</.btn></.actions>
      </:header>

      <.card title="Pads seen by this browser">
        <div :for={p <- @pads} class="line"><strong>{p["id"]}</strong><.badge on>{p["axes"]} axes · {p["buttons"]} buttons</.badge></div>
        <.hint :if={@pads == []}>No gamepad yet. Plug it in and press any button — browsers only reveal a pad after it's touched.</.hint>
      </.card>

      <.card title="What it's doing">
        <:aside><.badge on={@action != :idle} warn={@action == :stop}>{Gamepad.describe(@action)}</.badge></:aside>
        <.kv label="mount" value={@selected || "none"} />
        <.kv :if={@snap} label="position" value={"RA #{fmt1(@snap.axes.ra.degrees)}° · Dec #{fmt1(@snap.axes.dec.degrees)}°"} />
        <.kv :if={@start && @snap} label="moved" value={"ΔRA #{fmt1(@snap.axes.ra.degrees - elem(@start, 0))}° · ΔDec #{fmt1(@snap.axes.dec.degrees - elem(@start, 1))}°"} />
        <.hint>Hold the <strong>trigger</strong> (button 0) and tilt the ball: X turns the polar axis, Y the Dec axis; more tilt, more speed. D-pad nudges at 8×. Button 1 is STOP.</.hint>
      </.card>

      <.card :if={@state} title="Raw">
        <div class="axes">
          <div :for={{v, i} <- Enum.with_index(@state.axes)} class="axis-bar">
            <span class="axis-i">{i}</span>
            <div class="bar"><div class="fill" style={"left:#{50 + min(max(v, -1), 1) * 50 * (if v < 0, do: 1, else: 0) + (if v < 0, do: v * 50, else: 0)}%; width:#{abs(min(max(v, -1), 1)) * 50}%"}></div></div>
            <span class="axis-v">{fmt2(v)}</span>
          </div>
        </div>
        <div class="buttons">
          <span :for={{b, i} <- Enum.with_index(@state.buttons)} class={["btn-dot", (b["pressed"] || b[:pressed]) && "on"]}>{i}</span>
        </div>
        <.kv label="hat" value={if @state.hat, do: inspect(@state.hat), else: "centred"} />
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end

  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt2(x) when is_number(x), do: :erlang.float_to_binary(x * 1.0, decimals: 2)
  defp fmt2(_), do: "—"
end
