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
      # the live sky under the mount: the stars move on, so it's redrawn every 15 s
      :timer.send_interval(15_000, :sky)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       page_title: "Scope",
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       selected: params["id"] || session["id"] || session["telescope"],
       refs: %{},
       subscribed: MapSet.new(),
       snap: nil,
       tracker: nil
     )
     |> rescan()
     |> sky()
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

  def handle_info(:sky, socket), do: {:noreply, sky(socket)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket |> sky() |> compute()}

  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)
    assign(socket, refs: refs, subscribed: subscribed, selected: selected, snap: if(is_map(snap), do: snap), page_title: Controller.Words.title(selected, "Scope"))
  end

  # The sky now from the observatory's site, on the mount's own chart (hour
  # angle across, declination up): no time keys here, that's the Sky Map's job.
  defp sky(socket) do
    site = Pointing.site()
    trees? = Settings.get("horizon") != nil
    assign(socket, sky: Controller.Sky.Scene.build(DateTime.utc_now(), site, Settings.horizon(), view: :mount, trees: trees?), site_set: Pointing.site_set?())
  end

  # where the telescope points on that chart, from this snapshot
  defp crosshair(%{snap: %{connected: true} = snap, sky: sky, selected: id}) when is_map(sky) do
    ctx = Pointing.context(DateTime.utc_now(), id)

    with {ra, dec} <- Pointing.scope_radec(Map.put(snap, :homed, snap[:homed] == true), ctx),
         {x, y} <- Controller.Sky.Scene.place(sky, ra, dec) do
      %{x: x, y: y}
    else
      _ -> nil
    end
  rescue
    _ -> nil
  end

  defp crosshair(_), do: nil

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
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Mount", @selected)} />
        <.title>Scope</.title>
        <.actions>
          
          <.help href={~p"/docs/scope"} label="the scope drawing" />
          <.stop /></.actions>
      </:header>

      <Controller.Components.Status.status :if={@snap && !@nested} snap={@snap} id={@selected} compact />

      <%!-- the mount takes the room; what it's doing beside it (on a phone, below) --%>
      <.split :if={@pose}>
        <:main>
          <Controller.Components.Scope.scope pose={@pose} size={520} label={@selected} class="scope-hero" />
          <%!-- where it points, on the sky right now: the mount's own chart, live --%>
          <% cross = crosshair(assigns) %>
          <figure class="scope-sky">
            <Controller.Components.SkyChart.chart id="scope-sky" scene={@sky} scope={cross} label={"Where #{@selected} points: the sky now, hour angle across, declination up"} />
            <figcaption class="dim">
              The sky now from {if @site_set, do: "the observatory's site", else: "0° N, 0° E (Site not set)"}, in the mount's own axes: hour angle across, the meridian down the middle, declination up.
              {if cross, do: "The crosshair is the telescope.", else: "Where the telescope points isn't known yet: set home, or align."}
            </figcaption>
          </figure>
        </:main>
        <:side>
          <div class="state-line">
            <strong>{state_words(@snap, @tracker)}</strong>
            <span class="dim">Drawn from the encoders as it stands: the polar axis leans up from the tripod at your latitude, the Dec axis crosses its top with the tube on one end and the counterweight on the other. An arc beside an axis means it's turning.</span>
          </div>
          <%!-- this mount's setup isn't in the sidebar; the ways to move it are --%>
          <.row :if={@selected}>
            <.btn navigate={~p"/setup/#{@selected}"}>Setup ›</.btn>
          </.row>
        </:side>
      </.split>

      <.card :if={!@pose} title="No Mount">
        <.hint>Nothing is answering yet. Plug the EQDIR cable into this machine.</.hint>
        <.row><.btn navigate={~p"/devices"}>Devices ›</.btn></.row>
      </.card>

    </.page>
    """
  end

  defp state_words(nil, _), do: "Not connected"
  defp state_words(%{connected: false}, _), do: "Not answering"
  defp state_words(snap, tracker) do
    cond do
      tracker && tracker.paused -> "Tracking #{tracker.name}, paused"
      tracker -> "Tracking #{tracker.name}"
      snap.tracking != :off -> "Tracking at the #{snap.tracking} rate"
      Enum.any?(snap.axes, fn {_, ax} -> ax.running end) -> "Moving"
      snap.homed -> "Still, home set"
      true -> "Still, home not set"
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
