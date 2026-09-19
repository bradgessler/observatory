defmodule Controller.StartLive do
  @moduledoc """
  The front door is a flow, not a menu: plug in → zero the axes → star 1, 2, 3
  until the alignment locks → look at things. The page shows the step you are
  on and nothing from later steps; when the stars agree it turns into the
  control surface — tonight's targets with Go, what the tube is holding, the
  ways to centre, STOP. Everything else (the bench, the camera, the plumbing)
  is one link at the bottom.

  The steps are read from the same state every other page uses: the mount's
  snapshot (connected, zeroed), the star alignment (`Controller.Sky.Lineup`),
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
      changed? = socket.assigns.snap == nil or snap.homed != socket.assigns.snap.homed or snap.connected != socket.assigns.snap.connected
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

    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()
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
        do: Controller.SkyLive.targets(now, site, Settings.horizon(), Settings.get("aperture_mm", 100)) |> Enum.take(@targets_shown),
        else: []

    assign(socket,
      step: step,
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
    {:noreply, socket |> compute() |> notice("stopped")}
  end

  def handle_event("go", %{"id" => oid}, socket) do
    obj = Enum.find(socket.assigns.targets, &(&1.id == oid))
    ref = socket.assigns.refs[socket.assigns.selected]
    ctx = Pointing.context(DateTime.utc_now(), socket.assigns.selected)

    text =
      case obj && Pointing.slew(ref, socket.assigns.snap, obj, ctx, track: true) do
        {:ok, _, _} -> "heading to #{obj.name} — it will hold there"
        {:error, :limit} -> "#{obj.name} is outside the soft limits from here"
        {:error, :not_connected} -> "no mount"
        {:error, e} -> inspect(e)
        nil -> "gone from the list — try again"
      end

    {:noreply, notice(socket, text)}
  end

  def handle_event("release", _, socket) do
    Tracker.stop(socket.assigns.selected)
    {:noreply, socket |> compute() |> notice("released")}
  end

  def handle_event("pad", %{"on" => on}, socket) do
    on? = on == "true"
    if on? and socket.assigns.selected, do: safe(fn -> Input.target(socket.assigns.selected) end)
    safe(fn -> Input.arm(on?) end)
    {:noreply, socket |> compute() |> notice(if on?, do: "the pad moves #{socket.assigns.selected}", else: "pad: watch only")}
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
        <span class="home-brand">Observatory</span>
        <.title>{title(@step, @selected)}</.title>
        <.actions>
          <button class="stop-mini" phx-click="stop" aria-label="stop the mount">STOP</button>
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
        </.actions>
      </:header>

      <ol class="flow-steps" aria-label="setup steps">
        <li :for={{key, label} <- steps(@status)} class={state(key, @step)}>{label}</li>
      </ol>

      <%!-- step 1: nothing to talk to --%>
      <.card :if={@step == :plug} title="Plug In the Telescope">
        <.hint>Mount powered, EQDIR cable in this machine. This page moves on by itself.</.hint>
        <.kv :if={@snap} label="mount" value={"#{@selected} · not answering"} />
        <.row><.btn navigate={~p"/devices"}>What's plugged in ›</.btn></.row>
      </.card>

      <%!-- steps 2 and 3 are the star-align page, nested --%>
      <div :if={@step in [:zero, :stars]} class="flow-nested">
        <%= live_render(@socket, Controller.LineupLive, id: "start-align-#{@selected}", session: %{"id" => @selected, "nested" => true}) %>
      </div>

      <%!-- step 4: locked — control mode --%>
      <%= if @step == :look do %>
        <.card class="lineup-status ok">
          <div class="state-line">
            <strong>Locked · {@status.n} stars · agree to {fmt(@status.rms_arcmin)}′</strong>
            <span class="dim">{@status.axis_words} · good for {Enum.join(@status.good_for, " · ")}</span>
          </div>
          <.row>
            <.btn class="btn-ghost" navigate={~p"/controls/align/#{@selected}"}>Add a star ›</.btn>
            <.btn class="btn-ghost" navigate={~p"/setup/#{@selected}"}>How it's steered ›</.btn>
          </.row>
        </.card>

        <.card title="On Target" :if={@tracker}>
          <div class="state-line">
            <strong>{@tracker.name}{if @tracker.paused, do: " · paused while you drive", else: ""}</strong>
            <span class="dim">holding · RA {fmt(@tracker.ra_rate)}× · Dec {fmt(@tracker.dec_rate)}× · {if @tracker.error_arcmin, do: "#{fmt(@tracker.error_arcmin)}′ off", else: "settling"}</span>
          </div>
          <.row>
            <.btn variant="primary" navigate={~p"/controls/nudge/#{@selected}"}>Centre it ›</.btn>
            <.btn phx-click="release">Stop holding</.btn>
          </.row>
        </.card>

        <.card title="Look At">
          <div :for={t <- @targets} class="star-row">
            <div>
              <strong>{t.name}</strong>
              <span class="dim"> · {Lineup.where_words(t.alt, t.az)}{if t.words, do: " · " <> t.words, else: ""}</span>
            </div>
            <.btn variant="primary" phx-click="go" phx-value-id={t.id}>Go</.btn>
          </div>
          <.hint :if={@targets == []}>Nothing up right now.</.hint>
          <.row>
            <.btn navigate={~p"/sky/#{@selected}"}>Whole sky ›</.btn>
            <.btn navigate={~p"/sky/#{@selected}?tab=targets"}>Tonight's list ›</.btn>
          </.row>
        </.card>

        <.card title="Drive It">
          <.row>
            <.btn navigate={~p"/controls/nudge/#{@selected}"}>Nudge</.btn>
            <.btn navigate={~p"/controls/dpad/#{@selected}"}>Keypad</.btn>
            <.btn navigate={~p"/controls/tilt/#{@selected}"}>Tilt</.btn>
            <.btn navigate={~p"/controls/orb/#{@selected}"}>Orb</.btn>
          </.row>
          <%!-- a plugged-in pad shows itself here, with the one switch that matters --%>
          <div :if={@pads != []} class="star-row">
            <div>
              <strong>Pad</strong>
              <span class="dim"> · {Enum.map_join(@pads, ", ", & &1.parser)} · {pad_words(@mapper, @selected)}</span>
            </div>
            <.btn :if={!pad_on?(@mapper, @selected)} variant="primary" phx-click="pad" phx-value-on="true">Pad moves scope</.btn>
            <.btn :if={pad_on?(@mapper, @selected)} phx-click="pad" phx-value-on="false">Watch only</.btn>
          </div>
        </.card>
      <% end %>

      <.hint :if={@modes != []} class="flow-modes">
        <span :for={{label, detail} <- @modes}><b>{label}</b> · {detail}<br /></span>
      </.hint>

      <p class="flow-more">
        <.link navigate={~p"/all"}>Everything else ›</.link>
        · <.link href={~p"/docs/start"}>how this works</.link>
        · <.link navigate={~p"/events"}>events</.link>
      </p>

      <p :if={@notice} id={"notice-#{elem(@notice, 1)}"} class="notice">{elem(@notice, 0)}</p>
    </.page>
    """
  end

  defp steps(status) do
    n = if status, do: min(status.n, 3), else: 0
    [{:plug, "Plug in"}, {:zero, "Zero"}, {:stars, "Stars #{n}/3"}, {:look, "Look"}]
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

  defp title(:plug, _), do: "Setup"
  defp title(:zero, id), do: "#{id} · Setup"
  defp title(:stars, id), do: "#{id} · Star Align"
  defp title(:look, id), do: "#{id} · Locked"

  defp pad_on?(m, id), do: Map.get(m, :armed, false) and Map.get(m, :target) == id

  defp pad_words(m, id) do
    cond do
      pad_on?(m, id) -> "moves the scope"
      Map.get(m, :off_reason) -> m.off_reason
      Map.get(m, :ignoring) -> "held, but off"
      true -> "watch only"
    end
  end

  defp fmt(nil), do: "—"
  defp fmt(x), do: :erlang.float_to_binary(x / 1, decimals: 1)

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end
end
