defmodule Controller.CenterLive do
  @moduledoc """
  Center: move what you see in the eyepiece, not the axes. The round field is
  a touchpad, so an eye can stay at the eyepiece: put a thumb on it and pull
  the way you want the view to go; further is faster (0.5× to 8× sidereal,
  never a slew), and letting go stops it. Each touch is one direction: a
  thumb that means "up" drifts sideways without its owner knowing (the first
  night), so the first way a touch pulls, up/down or left/right, is the only
  way it drives until it lifts. **Centered** says the object is on
  the crosshair.

  Which axis moves the view which way depends on the side of the pier, the
  diagonal and how the eyepiece is turned, so it is a setting (`"view_map"`),
  not a guess: down and right, each an axis and a sign. The default is what
  the first night taught at the eyepiece (down is RA forward, right is Dec
  back). If a tap goes the other way, one tap on Backwards flips that pair,
  for every page and phone.
  """
  use Controller, :live_view
  import Controller.Components.UI
  require Logger

  alias Controller.Settings

  # the first night, EQ6-R, star diagonal: what moved the view down and right
  @view_map Controller.PadView.default_view_map()
  # tonight's eyepiece showed about 72′ across (5% was 0.06°)
  @field_arcmin 72
  # the drag: just past the dead zone crawls, the rim is brisk; nothing like a slew
  @slow 0.5
  @fast 8.0
  # what the RA motor already runs at while tracking, in sidereal units
  @track_units %{sidereal: 1.0, lunar: 0.966, solar: 0.997}

  @doc """
  View speed (× sidereal) for a pull of `mag` (0..1 past the dead zone):
  0.5× to 8× on a log scale, eased so the first half of the pull stays slow
  (1.3× at half way) and only the end is brisk.
  """
  def speed(mag) when mag <= 0, do: 0.0
  def speed(mag), do: @slow * :math.pow(@fast / @slow, :math.pow(min(mag, 1.0), 1.5))

  @doc "Which way a touch drives, decided by its first real pull: `:vertical` or `:horizontal`."
  def lock_for(x, y), do: if(abs(y) >= abs(x), do: :vertical, else: :horizontal)

  @doc "The pull kept to the locked direction, as a unit vector."
  def locked({x, _y}, :horizontal), do: {if(x >= 0, do: 1.0, else: -1.0), 0.0}
  def locked({_x, y}, :vertical), do: {0.0, if(y >= 0, do: 1.0, else: -1.0)}

  @doc """
  Axis rates (× sidereal, what to command) for a pull in the view: `x` right,
  `y` up, unit vector, at `speed`. RA carries on from the tracking rate so a
  drag moves the view relative to the sky, not relative to a stopped motor.
  """
  def drag_rates(x, y, speed, map \\ @view_map, tracking \\ :off) do
    [ax_r, s_r] = map["right"]
    [ax_d, s_d] = map["down"]

    rel =
      [{String.to_existing_atom(ax_r), x * s_r * speed}, {String.to_existing_atom(ax_d), -y * s_d * speed}]
      |> Enum.reduce(%{}, fn {a, r}, acc -> Map.update(acc, a, r, &(&1 + r)) end)

    for axis <- [:ra, :dec], r = Map.get(rel, axis, 0.0), abs(r) > 1.0e-9 do
      {axis, if(axis == :ra, do: Map.get(@track_units, tracking, 0.0) + r, else: r)}
    end
  end

  def default_view_map, do: @view_map

  @doc "The axis and signed step (degrees) that moves the view `dir` by `arcmin`."
  def move_for(dir, arcmin, map \\ @view_map) do
    {pair, sign} =
      case dir do
        "down" -> {"down", 1}
        "up" -> {"down", -1}
        "right" -> {"right", 1}
        "left" -> {"right", -1}
      end

    [axis, s] = Map.fetch!(map, pair)
    {String.to_existing_atom(axis), sign * s * arcmin / 60}
  end

  @doc """
  The map turned 90°: what moved the view down now moves it right, and what
  moved it right now moves it up. A star diagonal turned in its holder turns
  the view with it (the first night, between the Moon and Saturn); four turns
  are back where they started, and with the two flips every way the view can
  sit is one or two taps away.
  """
  def turn(map), do: %{"right" => map["down"], "down" => (fn [a, s] -> [a, -s] end).(map["right"])}

  @doc "The map with one pair (`\"down\"` or `\"right\"`) reversed."
  def flip(map, pair), do: Map.update!(map, pair, fn [axis, s] -> [axis, -s] end)

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("center")
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       view_map: Settings.get("view_map", @view_map),
       field: Settings.get("eyepiece_field_arcmin", @field_arcmin),
       refs: %{},
       selected: params["id"] || session["id"] || session["telescope"],
       snap: nil,
       last: nil,
       drag: nil,
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
  def handle_info({:settings, "view_map", v}, socket), do: {:noreply, assign(socket, view_map: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  # what the Centered press recorded (Controller.CenterPoints), from here or the game controller
  def handle_info({:centered_point, id, what}, socket) do
    if socket.assigns.snap && id == socket.assigns.snap.id do
      notice =
        case what do
          {:unknown, _} -> "Centered, but nothing is being tracked, so there's nothing to name. Go To something first."
          %{name: name, n: n} -> "Centered on #{name}: #{n} alignment point#{if n == 1, do: "", else: "s"}. Undo it on #{name}'s page."
        end

      {:noreply, assign(socket, notice: notice)}
    else
      {:noreply, socket}
    end
  end

  def handle_info({:centered, _}, socket), do: {:noreply, socket}

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

    assign(socket, refs: refs, selected: selected, snap: snap, page_title: Controller.Words.title(selected, "Center"))
  end

  @impl true
  # The Stick hook: "stick" every 250 ms while a thumb is down (x right, y up,
  # mag 0..1 past the dead zone), "stick_end" when it lifts or the page hides.
  # Every command carries the driver's hold, so a lost page stops within a second.
  def handle_event("stick", %{"x" => x, "y" => y, "mag" => mag}, socket) do
    tracking = (socket.assigns.drag && socket.assigns.drag.tracking) || (socket.assigns.snap && socket.assigns.snap.tracking) || :off
    v = speed(mag / 1)
    # the first real pull decides the direction for the whole touch
    lock = (socket.assigns.drag && socket.assigns.drag[:lock]) || if(v > 0, do: lock_for(x / 1, y / 1))
    {x, y} = if lock, do: locked({x / 1, y / 1}, lock), else: {x / 1, y / 1}
    rates = if v > 0, do: drag_rates(x, y, v, socket.assigns.view_map, tracking), else: []
    idle = for axis <- socket.assigns.held, not List.keymember?(rates, axis, 0), do: axis
    socket = Enum.reduce(idle, socket, fn axis, sk -> settle(sk, axis, tracking) end)
    socket = Enum.reduce(rates, socket, fn {axis, r}, sk -> run(sk, &Mount.slew(&1, axis, r, hold: true)) end)
    report(socket, %{view: {x, y}, speed: v, rates: rates})
    {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)), drag: %{x: x, y: y, speed: v, tracking: tracking, lock: lock}, last: nil)}
  end

  def handle_event("stick_end", _, socket) do
    tracking = (socket.assigns.drag && socket.assigns.drag.tracking) || :off
    socket = Enum.reduce(socket.assigns.held, socket, fn axis, sk -> settle(sk, axis, tracking) end)
    report(socket, %{rates: []})
    {:noreply, assign(socket, held: [], drag: nil)}
  end

  # Keys, for a keyboard or a screen reader: an arrow moves the view that way
  # at a middle speed while it's held (key repeat feeds the deadman), letting
  # go stops, Escape or space is STOP.
  @keys %{"ArrowUp" => {0.0, 1.0}, "ArrowDown" => {0.0, -1.0}, "ArrowLeft" => {-1.0, 0.0}, "ArrowRight" => {1.0, 0.0}}

  def handle_event("keydown", %{"key" => k}, socket) when k in [" ", "Escape"] do
    Controller.Sky.Tracker.stop_all()
    {:noreply, socket |> run(&Mount.emergency_stop/1) |> assign(held: [], drag: nil)}
  end

  def handle_event("keydown", %{"key" => k}, socket) when is_map_key(@keys, k) do
    {x, y} = @keys[k]
    handle_event("stick", %{"x" => x, "y" => y, "mag" => 0.5}, assign(socket, drag: nil))
  end

  def handle_event("keyup", %{"key" => k}, socket) when is_map_key(@keys, k), do: handle_event("stick_end", %{}, socket)
  def handle_event(k, _params, socket) when k in ["keydown", "keyup"], do: {:noreply, socket}

  def handle_event("turn", _, socket) do
    map = turn(socket.assigns.view_map)
    Settings.put("view_map", map)
    Telescope.Events.emit(:center, :turned, %{map: map})
    {:noreply, assign(socket, view_map: map, last: nil)}
  end

  def handle_event("flip", %{"pair" => pair}, socket) when pair in ["down", "right"] do
    map = flip(socket.assigns.view_map, pair)
    Settings.put("view_map", map)
    Telescope.Events.emit(:center, :flipped, %{pair: pair, map: map})
    {:noreply, assign(socket, view_map: map, last: nil)}
  end

  def handle_event("centered", _, socket) do
    case socket.assigns.snap do
      %{axes: %{ra: ra, dec: dec}} = snap ->
        at = DateTime.utc_now()
        data = %{mount: snap.id, ra: ra.degrees, dec: dec.degrees, at: DateTime.to_iso8601(at)}
        Logger.info("centered: #{snap.id} ra=#{ra.degrees} dec=#{dec.degrees} at=#{data.at}")
        Telescope.Events.emit(:center, :centered, data)
        Telescope.broadcast("center", {:centered, data})
        {:noreply, assign(socket, notice: "Centered at #{Calendar.strftime(at, "%H:%M:%S")} UTC", last: nil)}

      _ ->
        {:noreply, assign(socket, notice: "No mount")}
    end
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  # tell the Control Stack page: law 1, through the eyepiece map
  defp report(socket, what) do
    if id = socket.assigns.selected, do: Controller.Stack.note(id, Map.merge(%{law: 1, source: "Center touchpad"}, what))
  end

  # letting go of an axis: RA goes back to tracking if it was, Dec stops
  defp settle(socket, :ra, tracking) when tracking in [:sidereal, :lunar, :solar], do: run(socket, &Mount.track(&1, tracking))
  defp settle(socket, axis, _tracking), do: run(socket, &Mount.stop(&1, axis))

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "No mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> assign(socket, notice: nil)
            {:error, :limit} -> assign(socket, notice: "Soft limit")
            {:error, e} -> assign(socket, notice: Controller.Words.error(e))
          end
        catch
          :exit, _ -> assign(socket, notice: "Mount unreachable")
        end
    end
  end

  @impl true
  def render(assigns) do

    ~H"""
    <%!-- always the red night palette: this page is for the eyepiece, in the dark --%>
    <.page id="center" night={true} class={@nested && "nested"} phx-window-keydown="keydown" phx-window-keyup="keyup">
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Controls", @selected)} />
        <.title>Center</.title>
        <%!-- the Controls section's status: what the mount is doing and where it points --%>
        <.status label="Mount">{live_render(@socket, Controller.ControlsStatusLive, id: "controls-status", session: %{"id" => @selected})}</.status>
        <.actions><.help href={~p"/docs/center"} label="centering" /><.stop /></.actions>
      </:header>

      <%!-- the touchpad takes the room; Centered, the screen and the Backwards keys beside it (on a phone, below) --%>
      <.split class="center-split">
        <:main>
          <section id="center-pad" class="center-pad" phx-hook="Stick" data-origin="touch" data-reach="110" data-dead="0.18" role="application" aria-label="the eyepiece as a touchpad: pull the way you want the view to go, further is faster, let go to stop">
            <svg class="center-view" viewBox="-110 -110 220 220" aria-hidden="true">
              <circle r="100" class="center-disc" />
              <circle r="50" class="center-half" />
              <line x1="-100" y1="0" x2="-14" y2="0" class="center-cross" /><line x1="14" y1="0" x2="100" y2="0" class="center-cross" />
              <line x1="0" y1="-100" x2="0" y2="-14" class="center-cross" /><line x1="0" y1="14" x2="0" y2="100" class="center-cross" />
              <circle r="14" class="center-aim" />
              <g :if={@drag && @drag.speed > 0} class="center-moved" transform={"rotate(#{drag_angle(@drag)})"}>
                <line x1="0" y1="-18" x2="0" y2={-18 - arrow_len(@drag.speed)} /><path d={"M-9,#{-6 - arrow_len(@drag.speed)} L0,#{-20 - arrow_len(@drag.speed)} L9,#{-6 - arrow_len(@drag.speed)}"} />
              </g>
              <text x="0" y="-104" class="center-edge">up</text>
              <text x="0" y="110" class="center-edge">down</text>
              <text x="-104" y="4" class="center-edge" text-anchor="end">left</text>
              <text x="104" y="4" class="center-edge" text-anchor="start">right</text>
            </svg>
            <span class="center-knob" data-knob></span>
          </section>
        </:main>
        <:side>

          <p class="center-now" role="status">{now_words(@drag, @snap)}</p>

          <.btn class="center-done" phx-click="centered">Centered</.btn>
          <%!-- the phone stays lit while you're at the eyepiece (the Awake hook) --%>
          <button id="center-awake" type="button" class="btn" phx-hook="Awake" phx-update="ignore" aria-pressed="false">Keep Screen On</button>

          <p class="hint" role="status">{last_words(@last, @field)}</p>
          <div class="center-flip">
            <.btn phx-click="flip" phx-value-pair="down">Up/Down Backwards</.btn>
            <.btn phx-click="flip" phx-value-pair="right">Left/Right Backwards</.btn>
            <.btn phx-click="turn">Up/Down and Left/Right Swapped</.btn>
          </div>
        </:side>
      </.split>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # the drag drawn: pointing where the view is going, longer when faster
  defp drag_angle(%{x: x, y: y}), do: :math.atan2(x, y) * 180 / :math.pi()
  defp arrow_len(speed), do: round(20 + 50 * :math.log(speed / @slow) / :math.log(@fast / @slow))

  # what the mount is doing right now, from its own report: proof the thumb is working
  defp now_words(drag, snap) do
    motion =
      case snap do
        %{axes: %{ra: ra, dec: dec}} -> "RA #{axis_rate(ra)} · Dec #{axis_rate(dec)}"
        _ -> "no mount"
      end

    case drag do
      %{speed: v} when v > 0 -> "Moving the view #{way(drag)} at #{fmt_speed(v)}, #{if drag.lock == :vertical, do: "up/down", else: "left/right"} only until you lift · mount: #{motion}"
      _ -> "Put a thumb on the eyepiece and pull the way the view should go · mount: #{motion}"
    end
  end

  defp axis_rate(%{running: true, deg_per_s: d}) when is_number(d), do: "#{fmt_speed(abs(d) / (360 / 86_164.0905))}"
  defp axis_rate(_), do: "still"

  defp fmt_speed(v) when v < 10, do: "#{:erlang.float_to_binary(v, decimals: 1)}×"
  defp fmt_speed(v), do: "#{round(v)}×"

  defp way(%{x: x, y: y}) do
    v = if abs(y) >= 0.38, do: if(y > 0, do: "up", else: "down")
    h = if abs(x) >= 0.38, do: if(x > 0, do: "right", else: "left")
    [v, h] |> Enum.reject(&is_nil/1) |> Enum.join(" and ")
  end

  defp last_words(_, _), do: "If the view goes the other way from your pull, tap Up/Down Backwards or Left/Right Backwards; if up/down moves it sideways, tap Up/Down and Left/Right Swapped. It stays that way for this setup."
end
