defmodule Controller.ScopeLive do
  @moduledoc """
  The telescope, right now: what it is doing (still, tracking, slewing, with
  how far a slew has got), what it is seeing (the camera's latest picture
  and how old it is), where it points on the sky, the mount itself drawn
  from its encoders, and a log of what has happened to it, newest first.
  Nothing to drive here: this is the page you leave open, and the page the
  bar at the top of every page opens.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Components.Scope
  alias Controller.{ScopeNow, Settings, StillCamera}
  alias Controller.Components.Pictures
  alias Controller.Sky.{Pointing, Tracker}

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("tracker")
      # what it sees, and what happens to it
      StillCamera.subscribe()
      Telescope.Events.subscribe()
      Process.send_after(self(), :tick, 1_000)
      # the live sky under the mount: the stars move on, so it's redrawn every 15 s
      :timer.send_interval(15_000, :sky)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       page_title: "Now",
       cam: safe(fn -> StillCamera.find() end),
       now_ms: System.system_time(:millisecond),
       log: [],
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
     |> compute()
     |> log()}
  end

  # what has happened to this telescope, newest first: the events that name it
  @log 25
  defp log(socket), do: assign(socket, log: Telescope.Events.recent(400) |> Enum.filter(&about?(&1, socket.assigns.selected)) |> Enum.take(@log))

  defp about?(%{data: %{id: id}}, id) when is_binary(id), do: true
  defp about?(_, _), do: false

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

  def handle_info({:event, e}, socket) do
    if about?(e, socket.assigns.selected), do: {:noreply, assign(socket, log: Enum.take([e | socket.assigns.log], @log))}, else: {:noreply, socket}
  end

  def handle_info({:still_camera, cam}, socket), do: {:noreply, assign(socket, cam: StillCamera.prefer(socket.assigns.cam, cam))}

  def handle_info(:tick, socket) do
    Process.send_after(self(), :tick, 1_000)
    {:noreply, assign(socket, now_ms: System.system_time(:millisecond))}
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
    assigns = assign(assigns, now: (assigns[:scope_now] || %{})[assigns.selected] || ScopeNow.summary(assigns.snap, assigns.tracker))

    ~H"""
    <.page id="scope" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Telescope", @selected)} />
        <.title>Now</.title>
        <.actions>
          <.help href={~p"/docs/scope"} label="the telescope's page" />
          <.stop />
        </.actions>
      </:header>

      <.split :if={@pose}>
        <:main>
          <%!-- what it is seeing: the camera's latest picture, how old it is, and the one being taken --%>
          <section :if={@cam && @cam.camera} class="now-part" aria-labelledby="now-seeing">
            <h2 id="now-seeing" class="now-h">Seeing</h2>
            <section class="scope-frame" aria-label="latest picture">
              <img :if={@cam.last && @cam.last[:w]} src={StillCamera.src(@cam, @cam.last.seq)} alt={"Latest picture, taken #{Pictures.age_words(@cam.last, @now_ms)}"} />
              <div :if={!(@cam.last && @cam.last[:w])} class="scope-frame-empty"><p class="dim">No picture yet</p></div>
              <p :if={@cam.last && @cam.last[:w]} class="dim">Taken {Pictures.age_words(@cam.last, @now_ms)} with the {@cam.camera[:model] || "camera"}</p>
              <Pictures.taking :if={@cam.busy} shot={@cam[:shot]} now_ms={@now_ms} />
            </section>
            <.link navigate={~p"/cameras/telescope"} class="now-more">Telescope Camera ›</.link>
          </section>

          <%!-- where it points, on the sky right now: the mount's own chart, live --%>
          <% cross = crosshair(assigns) %>
          <section class="now-part" aria-labelledby="now-points">
            <h2 id="now-points" class="now-h">Where It Points</h2>
            <figure class="scope-sky">
              <Controller.Components.SkyChart.chart id="scope-sky" scene={@sky} scope={cross} label={"Where #{@selected} points: the sky now, hour angle across, declination up"} />
              <figcaption class="dim">
                The sky now from {if @site_set, do: "the telescope's location", else: "0° N, 0° E (location not set)"}, as the mount turns through it: hour angle across, the meridian down the middle, declination up. Grey is below the horizon.
                {if cross, do: "The crosshair is the telescope.", else: "Where the telescope points isn't known yet: set home, or align."}
              </figcaption>
            </figure>
            <.link navigate={~p"/sky/#{@selected}"} class="now-more">Sky Map ›</.link>
          </section>

          <%!-- the mount itself, posed from its encoders --%>
          <section class="now-part" aria-labelledby="now-mount">
            <h2 id="now-mount" class="now-h">The Mount</h2>
            <Controller.Components.Scope.scope pose={@pose} size={420} label={@selected} class="scope-hero" />
            <p class="dim">Drawn from the encoders as it stands: the polar axis leans up from the tripod, the Dec axis crosses its top with the tube on one end and the counterweight on the other. An arc beside an axis means it is turning.</p>
          </section>
        </:main>
        <:side>
          <%!-- what it is doing --%>
          <section class={["now-doing", @now && "now-#{@now.state}"]} aria-labelledby="now-doing-h">
            <h2 id="now-doing-h" class="now-h">Doing</h2>
            <div class="state-line">
              <strong role="status">{if @now, do: @now.words, else: state_words(@snap, @tracker)}</strong>
              <span :if={@now && @now.where}>{@now.where}</span>
            </div>
            <%!-- a slew: how far it has got, as a bar and in degrees to go on each axis --%>
            <div :if={@now && @now[:slew]} class="now-slew">
              <progress max="100" value={@now.slew.pct} aria-label="slew progress"></progress>
              <span>{@now.slew.pct}% · RA axis {fmt1(@now.slew.ra)}° to go · Dec axis {fmt1(@now.slew.dec)}° to go</span>
            </div>
            <Controller.Components.Status.status :if={@snap} snap={@snap} id={@selected} compact />
          </section>

          <.items label="about this telescope">
            <.link_item navigate={~p"/alignment/#{@selected}"} label="Alignment" detail={alignment_words((assigns[:alignments] || %{})[@selected])} />
            <.link_item navigate={~p"/setup/#{@selected}"} label="Setup" detail="How it is steered, home, the counterweight's side" />
          </.items>

          <%!-- what has happened to it, newest first --%>
          <section class="now-part" aria-labelledby="now-log">
            <h2 id="now-log" class="now-h">Log</h2>
            <p :if={@log == []} class="dim">Nothing yet. Every Go To, stop and alignment point shows here as it happens.</p>
            <ol :if={@log != []} class="events" aria-label="what has happened to this telescope, newest first">
              <li :for={e <- @log}>
                <time datetime={Calendar.strftime(e.at, "%Y-%m-%dT%H:%M:%SZ")}>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
                <span class="ev-what">{Controller.EventsLive.words(e)}</span>
              </li>
            </ol>
            <.link navigate={~p"/events"} class="now-more">All Events ›</.link>
          </section>
        </:side>
      </.split>

      <.card :if={!@pose} title="No Mount">
        <.hint>Nothing is answering yet. Plug the EQDIR cable into this machine.</.hint>
        <.row><.btn navigate={~p"/devices"}>Devices ›</.btn></.row>
      </.card>

    </.page>
    """
  end

  defp fmt1(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp fmt1(_), do: "?"

  defp alignment_words(%{words: words}), do: words
  defp alignment_words(_), do: "Not aligned"

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
