defmodule Controller.StartLive do
  @moduledoc """
  The front door is a flow, not a menu: plug in → set home → star 1, 2, 3
  until the alignment is good → look at things. The page shows the step you are
  on and nothing from later steps; when the stars agree it turns into the
  control surface — tonight's targets with Go To, what the mount is tracking,
  the ways to center, STOP. Everything else (the controls, the cameras, the
  system pages) is in the sidebar, Home and Search, not repeated here.

  The steps are read from the same state every other page uses: the mount's
  snapshot (connected, home set), the star alignment (`Controller.Sky.Lineup`),
  the tracker. Nothing here is remembered per browser, so two phones show
  the same step.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Controller.Sky.{Lineup, Pointing, Tracker}

  # locked = three stars that agree well enough to land things in an eyepiece
  @lock_goal "just look"
  @targets_shown 8

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("tracker")
      Telescope.subscribe("input")
      :timer.send_interval(10_000, :tick)
    end

    {:ok,
     socket
     |> assign(night: Settings.get("night", false), refs: %{}, subscribed: MapSet.new(), selected: params["id"], snap: nil, notice: nil)
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> compute()}
  end

  def handle_info(:tick, socket), do: {:noreply, compute(socket)}

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected do
      # the step changes on zeroed/connected, not on every 250 ms position
      old = socket.assigns.snap
      changed? = old == nil or snap.homed != old.homed or snap.connected != old.connected or snap[:homed_at] != old[:homed_at]
      socket = assign(socket, snap: snap)
      {:noreply, if(changed?, do: compute(socket), else: socket)}
    else
      {:noreply, socket}
    end
  end

  def handle_info({:tracker, id, status}, socket) do
    if id == socket.assigns.selected, do: {:noreply, assign(socket, tracker: status)}, else: {:noreply, socket}
  end

  def handle_info({:mapper, status}, socket), do: {:noreply, assign(socket, mapper: status)}
  def handle_info({:input, _, _}, socket), do: {:noreply, socket}
  def handle_info({:input_gone, _}, socket), do: {:noreply, compute(socket)}

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "lineup", _}, socket), do: {:noreply, compute(socket)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)
    assign(socket, refs: refs, subscribed: subscribed, selected: selected, snap: if(is_map(snap), do: snap))
  end

  # Which step, and what that step needs.
  defp compute(socket) do
    id = socket.assigns.selected
    snap = socket.assigns.snap
    status = id && Lineup.status(id)
    locked? = status != nil and status.n >= 3 and @lock_goal in status.good_for

    step =
      cond do
        is_nil(snap) or not snap.connected -> :plug
        not snap.homed -> :zero
        not locked? -> :stars
        true -> :look
      end

    now = DateTime.utc_now()
    site = Pointing.site()

    targets =
      if step == :look,
        do: Controller.SkyLive.targets(now, site, Settings.horizon(), Settings.get("aperture_mm", 100)) |> Enum.reject(&(&1.status == :rising)) |> Enum.take(@targets_shown),
        else: []

    assign(socket,
      step: step,
      page_title: start_title(id) <> " · " <> (steps(status) |> List.keyfind(step, 0) |> elem(1)),
      status: status,
      targets: targets,
      tracker: id && Tracker.status(id),
      pads: safe(fn -> Input.devices() end) || [],
      mapper: safe(fn -> Input.status() end) || %{armed: false, target: nil, off_reason: nil},
      now: now,
      modes: Controller.Modes.active()
    )
  end

  # -- events -------------------------------------------------------------------------

  @impl true
  def handle_event("stop", _, socket) do
    if id = socket.assigns.selected, do: Tracker.stop(id)
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.stop(ref) end)
    {:noreply, socket |> compute() |> notice("Stopped")}
  end

  def handle_event("go", %{"id" => oid}, socket) do
    obj = Enum.find(socket.assigns.targets, &(&1.id == oid))
    ref = socket.assigns.refs[socket.assigns.selected]
    ctx = Pointing.context(DateTime.utc_now(), socket.assigns.selected)

    text =
      case obj && (if moving?(socket.assigns.snap, socket.assigns.tracker), do: {:error, :moving}, else: Pointing.slew(ref, socket.assigns.snap, obj, ctx, track: true)) do
        {:error, :moving} -> "Still moving: let go, or wait for it to land"
        {:ok, _, _} -> "Going to #{obj.name}"
        {:error, :limit} -> "#{obj.name} is outside the soft limits from here"
        {:error, :not_connected} -> "No mount"
        {:error, e} -> Controller.Words.error(e)
        nil -> "Not on the list any more"
      end

    {:noreply, notice(socket, text)}
  end

  # the target is centred in the eyepiece right now: that is one more alignment
  # star, so the model tightens as the night goes on
  def handle_event("centred", _, socket) do
    case {socket.assigns.snap, socket.assigns.tracker} do
      {%{homed: true} = snap, %{target: %{ra_deg: ra, dec_deg: dec, name: name}}} ->
        st = Lineup.add(snap, %{name: name, ra_deg: ra, dec_deg: dec})
        {:noreply, socket |> compute() |> notice("#{name} added · #{st.n} stars · agree to #{fmt(st.rms_arcmin)}′")}

      _ ->
        {:noreply, notice(socket, "Nothing being tracked")}
    end
  end

  def handle_event("release", _, socket) do
    Tracker.stop(socket.assigns.selected)
    {:noreply, socket |> compute() |> notice("Stopped tracking")}
  end

  def handle_event("pad", %{"on" => on}, socket) do
    on? = on == "true"
    if on? and socket.assigns.selected, do: safe(fn -> Input.target(socket.assigns.selected) end)
    safe(fn -> Input.arm(on?) end)
    {:noreply, socket |> compute() |> notice(if on?, do: "The game controller moves #{socket.assigns.selected}", else: "Game controller: watch only")}
  end

  def handle_event("night", _, socket) do
    v = !socket.assigns.night
    Settings.put("night", v)
    {:noreply, assign(socket, night: v)}
  end

  defp notice(socket, text), do: assign(socket, notice: {text, System.unique_integer([:positive])})

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="start" night={@night} class="start">
      <:header>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Alignment", @selected && short(@selected))} />
        <.title>Status</.title>
        <%!-- the Alignment section's status: how well this telescope is aligned, the same as the sidebar's --%>
        <.status label="Alignment"><Controller.Components.AlignmentStatus.bar summary={(assigns[:alignments] || %{})[@selected]} /></.status>
        <.actions>
          <.help href={~p"/docs/start"} label="the start flow" />
          <.stop />
        </.actions>
      </:header>

      <ol class="flow-steps" aria-label="setup steps">
        <li :for={{key, label} <- steps(@status)} class={state(key, @step)} aria-current={if key == @step, do: "step"}>{label}<span :if={state(key, @step) == "done"} role="img" aria-label="done"> ✓</span></li>
      </ol>

      <%!-- the scope's live state, one line, on every step that has a scope --%>
      <Controller.Components.Status.status :if={@snap && @snap.connected} snap={@snap} id={@selected} compact />

      <%!-- step 1: nothing to talk to --%>
      <.card :if={@step == :plug} title="Plug In the Telescope">
        <.hint>Mount powered, EQDIR cable in this machine. This page moves on by itself.</.hint>
        <.kv :if={@snap} label="Mount" value={"#{@selected} · not answering"} />
        <.row><.btn navigate={~p"/devices"}>Devices ›</.btn></.row>
      </.card>

      <%!-- the two ways to add alignment points, side by side: centring stars (here, below) or photos --%>
      <.items :if={@step == :stars} label="ways to add alignment points" class="align-ways">
        <.link_item navigate={~p"/controls/align/#{@selected}"} label="Align by Stars" detail="Center a few stars in the eyepiece, one at a time: the steps are below" />
        <.link_item navigate={~p"/align/photo/#{@selected}"} label="Align by Photo" detail="Photos through the eyepiece, plate solved: also says which bolt to turn" />
      </.items>

      <%!-- steps 2 and 3 are Align by Stars, nested --%>
      <div :if={@step in [:zero, :stars]} class="flow-nested">
        <%= live_render(@socket, Controller.LineupLive, id: "start-align-#{@selected}", session: %{"id" => @selected, "nested" => true}) %>
      </div>

      <%!-- step 4: locked — control mode --%>
      <%= if @step == :look do %>
        <%!-- how well: the toolbar says; here, tighten it or see how it steers --%>
        <.hint :if={@status.axis_words}>{@status.axis_words}</.hint>
        <.row>
          <.btn variant="ghost" navigate={~p"/controls/align/#{@selected}"}>Add a Star ›</.btn>
          <.btn variant="ghost" navigate={~p"/align/photo/#{@selected}"}>Add by Photo ›</.btn>
          <.btn variant="ghost" navigate={~p"/setup/#{@selected}"}>How It's Steered ›</.btn>
        </.row>

        <.card title="On Target" :if={@tracker}>
          <div class="state-line">
            <strong>{@tracker.name}{cond do @tracker.paused == :goto -> " · slewing"; @tracker.paused -> " · paused while you drive"; true -> "" end}</strong>
            <span class="dim">Tracking · RA {fmt(@tracker.ra_rate)}× · Dec {fmt(@tracker.dec_rate)}× · {if @tracker.error_arcmin, do: "#{fmt(@tracker.error_arcmin)}′ off", else: "settling"}</span>
          </div>
          <.row>
            <.btn variant="primary" navigate={~p"/controls/eyepiece/#{@selected}"}>Center It ›</.btn>
            <.btn :if={@tracker[:target] && @tracker.target[:ra_deg]} phx-click="centred" aria-label={"Centered: #{@tracker.name} is in the middle of the eyepiece"}>Centered</.btn>
            <.btn phx-click="release">Stop Tracking</.btn>
          </.row>
          <.row>
            <.btn :if={@tracker[:target] && @tracker.target[:id]} variant="ghost" navigate={~p"/object/#{@tracker.target.id}?#{[mount: @selected, from: "start"]}"}>About {@tracker.name} ›</.btn>
            <.btn variant="ghost" navigate={~p"/setup/#{@selected}"}>Corrections ›</.btn>
          </.row>
        </.card>

        <.card title="Corrections">
          <Controller.Components.Corrections.corrections law={3} status={@status} model={Lineup.model(@selected)} lat={Pointing.site().lat} tracker={@tracker} compact />
        </.card>

        <.card title="Look At">
          <.items :if={@targets != []} label="tonight's targets">
            <.item :for={t <- @targets} as="li" label={t.name} detail={Lineup.where_words(t.alt, t.az) <> if(t.words, do: " · " <> t.words, else: "")}>
              <.btn variant="primary" phx-click="go" phx-value-id={t.id} aria-label={"Go To #{t.name}"}>Go To</.btn>
            </.item>
          </.items>
          <.hint :if={@targets == []}>Nothing up right now.</.hint>
          <%!-- the rest of this list; every other page is in the sidebar, Home and Search --%>
          <.row>
            <.btn navigate={~p"/tonight/#{@selected}"}>Tonight's List ›</.btn>
          </.row>
        </.card>

        <%!-- a plugged-in pad shows itself here, with the one switch that matters; the
              ways to move the scope are in the sidebar's Controls, not repeated here --%>
        <.card :if={@pads != []} title="Drive It">
          <.item label="Game controller" detail={Enum.map_join(@pads, ", ", & &1.parser) <> " · " <> pad_words(@mapper, @selected)}>
            <.btn :if={!pad_on?(@mapper, @selected)} variant="primary" phx-click="pad" phx-value-on="true">Moves the Mount</.btn>
            <.btn :if={pad_on?(@mapper, @selected)} phx-click="pad" phx-value-on="false">Watch Only</.btn>
          </.item>
        </.card>
      <% end %>

      <.hint :if={@modes != []} class="flow-modes">
        <span :for={{label, detail} <- @modes}><b>{label}</b> · {detail}<br /></span>
      </.hint>

      <p class="flow-more">
        <.link href={~p"/docs/start"}>How This Works</.link>
      </p>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp steps(status) do
    n = if status, do: min(status.n, 3), else: 0
    [{:plug, "Plug In"}, {:zero, "Set Home"}, {:stars, "Stars #{n}/3"}, {:look, "Look"}]
  end

  @order [:plug, :zero, :stars, :look]
  defp state(key, step) do
    i = Enum.find_index(@order, &(&1 == key))
    j = Enum.find_index(@order, &(&1 == step))

    cond do
      i < j -> "done"
      i == j -> "now"
      true -> "later"
    end
  end

  # the nav calls this page Start; the step strip under the title says which step
  defp start_title(nil), do: "Alignment"
  defp start_title(id), do: Controller.Words.title(short(id), "Alignment")

  # a serial port's name is long and mostly noise in a header: keep the tail that tells cables apart
  defp short("cu.usbserial-" <> tail), do: tail
  defp short("ttyUSB" <> _ = id), do: id
  defp short(id), do: id

  # a goto in flight, or an axis running that is not the tracker's own hold
  defp moving?(%{axes: axes}, tracker) when is_map(axes) do
    Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end) or
      (is_nil(tracker) and Enum.any?(axes, fn {_, ax} -> ax.running end))
  end

  defp moving?(_, _), do: false

  defp pad_on?(m, id), do: Map.get(m, :armed, false) and Map.get(m, :target) == id

  defp pad_words(m, id) do
    cond do
      pad_on?(m, id) -> "Moves the mount"
      Map.get(m, :off_reason) -> m.off_reason
      Map.get(m, :ignoring) -> "Held, but off"
      true -> "Watch only"
    end
  end

  defp fmt(nil), do: Controller.Words.none()
  defp fmt(x), do: :erlang.float_to_binary(x / 1, decimals: 1)

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end
end
