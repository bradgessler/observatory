defmodule Controller.ScopeLive do
  @moduledoc """
  The mount as a picture, posed from the encoders and redrawn on every
  snapshot. Nothing to drive here: this is the page you leave open to see
  what the telescope is doing.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Components.Scope
  alias Controller.Settings
  alias Controller.Sky.{Pointing, Tracker}

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("tracker")
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       page_title: "Scope",
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       selected: params["id"] || session["id"],
       refs: %{},
       subscribed: MapSet.new(),
       snap: nil,
       tracker: nil
     )
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> compute()}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, compute(assign(socket, snap: snap))}, else: {:noreply, socket}
  end

  def handle_info({:tracker, id, status}, socket) do
    if id == socket.assigns.selected, do: {:noreply, compute(assign(socket, tracker: status))}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, compute(socket)}

  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)
    assign(socket, refs: refs, subscribed: subscribed, selected: selected, snap: if(is_map(snap), do: snap))
  end

  defp compute(%{assigns: %{snap: nil}} = socket), do: assign(socket, pose: nil)

  defp compute(socket) do
    id = socket.assigns.selected
    ctx = Pointing.context(DateTime.utc_now(), id)
    tracker = socket.assigns.tracker || Tracker.status(id)
    assign(socket, pose: Scope.pose_from(socket.assigns.snap, ctx, tracker: tracker), tracker: tracker)
  end

  @impl true
  def handle_event("stop", _, socket) do
    if id = socket.assigns.selected, do: Tracker.stop(id)
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.stop(ref) end)
    {:noreply, socket}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="scope" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" />
        <.title>{@selected} · Scope</.title>
        <.actions>
          <.stop />
          <.help href={~p"/docs/scope"} label="the scope drawing" />
        </.actions>
      </:header>

      <Controller.Components.Status.status :if={@snap && !@nested} snap={@snap} id={@selected} compact />

      <.card :if={@pose} class="wide">
        <Controller.Components.Scope.scope pose={@pose} size={420} label={@selected} />
        <div class="state-line">
          <strong>{state_words(@snap, @tracker)}</strong>
          <span class="dim">Blue is the polar axis, green the Dec axis; a dashed arc means that axis is turning.</span>
        </div>
      </.card>

      <.card :if={!@pose} title="No Mount">
        <.hint>Nothing is answering yet. Plug the telescope cable into this machine.</.hint>
        <.row><.btn navigate={~p"/devices"}>What's Plugged In ›</.btn></.row>
      </.card>

      <.row :if={@selected}>
        <.btn navigate={~p"/controls/nudge/#{@selected}"}>Nudge</.btn>
        <.btn navigate={~p"/bench/strips?#{[mount: @selected]}"}>Axis Strips</.btn>
        <.btn navigate={~p"/setup/#{@selected}"}>Setup ›</.btn>
      </.row>
    </.page>
    """
  end

  defp state_words(nil, _), do: "Not connected"
  defp state_words(%{connected: false}, _), do: "Not answering"
  defp state_words(snap, tracker) do
    cond do
      tracker && tracker.paused -> "Holding #{tracker.name}, paused"
      tracker -> "Holding #{tracker.name}"
      snap.tracking != :off -> "Tracking at the #{snap.tracking} rate"
      Enum.any?(snap.axes, fn {_, ax} -> ax.running end) -> "Moving"
      snap.homed -> "Still, zeroed"
      true -> "Still, not zeroed"
    end
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end
end
