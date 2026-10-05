defmodule Controller.StackLive do
  @moduledoc """
  The control stack, live (#62): every layer between a hand and the motors,
  what each is correcting, and which ones the current input is working
  through. A pro scans the rows; anyone can tap a row for a live page that
  says what it is, where the number comes from and what to do about it
  (`Controller.Stack.Terms`).

  Everything that follows from the motors is recomputed on every mount report
  (as often as the driver sends them): where the target should be now, how
  far off the mount is now, the Moon's shift at this second. The hold only
  acts every 20 s; this page shows what it sees in between. Controls report
  through `Controller.Stack.note/2`. Nothing here moves the mount except STOP.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Settings, Stack}
  alias Controller.Stack.Terms
  alias Controller.Sky.{Astro, Ephemeris, Model, Pointing}

  @sidereal 360 / 86_164.0905
  # how long a hand's input keeps its layers marked "working now"
  @fresh_s 4
  # the hold reports every 20 s; quieter than this and it has stopped
  @fresh_loop_s 45
  @bodies %{"moon" => :moon, "mercury" => :mercury, "venus" => :venus, "mars" => :mars, "jupiter" => :jupiter, "saturn" => :saturn}

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      :timer.send_interval(1_000, :tick)
      Settings.subscribe()
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       view_map: Settings.get("view_map", Controller.PadView.default_view_map()),
       field: Settings.get("eyepiece_field_arcmin", 72),
       refs: %{},
       selected: params["id"] || session["id"] || session["telescope"],
       term: params["term"],
       snap: nil,
       events: %{},
       latest: nil,
       topic: nil,
       now: DateTime.utc_now()
     )
     |> rescan()}
  end

  @impl true
  def handle_params(params, _uri, socket), do: {:noreply, assign(socket, term: params["term"])}

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap, now: DateTime.utc_now())}, else: {:noreply, socket}
  end

  # the hold's routine check is background; anything else is someone driving
  def handle_info({:control, id, e}, socket) do
    if id == socket.assigns.selected do
      events = Map.put(socket.assigns.events, e.law, e)
      latest = if e.law == 5 and e[:action] != :hand, do: socket.assigns.latest, else: e
      {:noreply, assign(socket, events: events, latest: latest)}
    else
      {:noreply, socket}
    end
  end

  def handle_info({:settings, "view_map", v}, socket), do: {:noreply, assign(socket, view_map: v)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()

    socket =
      if selected && socket.assigns.topic != Stack.topic(selected) do
        if socket.assigns.topic, do: Telescope.unsubscribe(socket.assigns.topic)
        if connected?(socket), do: Telescope.subscribe(Stack.topic(selected))
        # open on the real state: the last word from each layer
        events = Stack.last(selected)
        latest = events |> Map.values() |> Enum.reject(&(&1.law == 5)) |> Enum.max_by(& &1.at, DateTime, fn -> nil end)
        assign(socket, topic: Stack.topic(selected), events: events, latest: latest)
      else
        socket
      end

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    assign(socket, refs: refs, selected: selected, snap: snap || socket.assigns.snap, page_title: Controller.Words.title(selected, "Control Stack"))
  end

  @impl true
  def handle_event("estop", _, socket) do
    Controller.Sky.Tracker.stop_all()
    with ref when not is_nil(ref) <- socket.assigns.refs[socket.assigns.selected], do: Mount.emergency_stop(ref)
    {:noreply, socket}
  end

  # -- what follows from the motors, now ------------------------------------------------------

  defp age(%{at: %DateTime{} = at}, now), do: DateTime.diff(now, at)
  defp age(_, _), do: nil

  defp driving(a) do
    case a.latest do
      %{law: law} = e when law != 5 -> if age(e, a.now) <= @fresh_s, do: e
      _ -> nil
    end
  end

  defp holding(a) do
    case a.events[5] do
      nil -> nil
      e -> if age(e, a.now) <= @fresh_loop_s, do: e
    end
  end

  # the layers working now: a hand's input, else the hold
  defp working(a) do
    cond do
      e = driving(a) -> Stack.path(e.law)
      holding(a) -> Stack.path(5)
      true -> []
    end
  end

  defp model(a), do: (a.events[5] || %{})[:model] || (a.events[3] || %{})[:model]
  defp target(a), do: (a.events[5] || %{})[:target] || (a.events[3] || %{})[:target]

  # where the target is at `at`, as seen from here
  defp target_at(%{name: name} = t, at, site) do
    case Map.fetch(@bodies, String.downcase(name)) do
      {:ok, body} ->
        p = Ephemeris.position(body, at, site)
        {p.ra_deg, p.dec_deg}

      :error ->
        {t.ra_deg, t.dec_deg}
    end
  end

  # The hold's own sum, done on every mount report: where the target's
  # encoders should be now (where it was last centred, plus the model's motion
  # since) against where they are. The hold corrects past 0.5′.
  defp live_error(a) do
    with %{anchor: %{at: t0, ra: e0_ra, dec: e0_dec}, target: tgt, model: %{params: p, signs: signs}} <- a.events[5],
         %{axes: %{ra: ra, dec: dec}} <- a.snap do
      site = Pointing.site()

      enc = fn t ->
        {ra_, dec_} = target_at(tgt, t, site)
        {alt, az} = Astro.alt_az(ra_, dec_, site.lat, Astro.lst_deg(t, site.lon))
        Model.encoders(p, signs, alt, az)
      end

      {m0r, m0d} = enc.(t0)
      {mr, md} = enc.(a.now)
      {(e0_ra + (mr - m0r) - ra.degrees) * 60, (e0_dec + (md - m0d) - dec.degrees) * 60}
    else
      _ -> nil
    end
  rescue
    _ -> nil
  end

  # -- rows: key, label, value, tone --------------------------------------------------------------

  defp rows(5, a) do
    case {holding(a), live_error(a)} do
      {nil, _} ->
        [row("hold", "Tracking", "nothing: sidereal tracking, if on, is the RA motor alone", :off)]

      {e, {dr, dd}} ->
        off = max(abs(dr), abs(dd))
        [row("hold", "Tracking", "#{target_name(e)}, #{arcmin(off)} off now", if(off < 1, do: :good, else: :caution))]

      {e, nil} ->
        [row("hold", "Tracking", target_name(e), :good)]
    end
  end

  defp rows(4, a) do
    t = target(a)
    site = Pointing.site()

    {parallax, ptone} =
      cond do
        is_nil(t) ->
          {"no target", :off}

        String.downcase(t.name) == "moon" ->
          g = Ephemeris.position(:moon, a.now)
          p = Ephemeris.position(:moon, a.now, site)
          {"#{arcmin(Astro.separation_radec(g.ra_deg, g.dec_deg, p.ra_deg, p.dec_deg) * 60)}, applied", :good}

        true ->
          {"none to speak of for #{t.name}", :good}
      end

    refraction =
      if t do
        {ra, dec} = target_at(t, a.now, site)
        {alt, _} = Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(a.now, site.lon))
        r = if alt > -1, do: 1.02 / :math.tan((alt + 10.3 / (alt + 5.11)) * :math.pi() / 180), else: 0.0
        "#{arcmin(r)} at #{round(alt)}° up, not applied"
      else
        "not applied"
      end

    [
      row("parallax", "The Moon's shift from where you stand", parallax, ptone),
      row("precession", "Star positions, year 2000 to today", "built in", :good),
      row("refraction", "Air bending starlight", refraction, :caution),
      row("cone", "Tube not square to its axis", "not measured", :unknown),
      row("square", "Axes not square to each other", "not measured", :unknown),
      row("flexure", "The tube sagging", "not measured", :unknown),
      row("backlash", "Slack in the gears", "not measured", :unknown),
      row("pe", "Wobble in the drive gear", "not measured", :unknown)
    ]
  end

  defp rows(3, a) do
    case model(a) do
      nil ->
        [row("points", "What the alignment rests on", "no alignment yet", :off)]

      m ->
        margin = 2 * m.rms

        [
          row("polar", "Where the mount's axis points", "#{deg1(m.off_pole)} from the pole", if(m.off_pole < 0.5, do: :good, else: :caution)),
          row("tripod", "Tripod tilt", "unknown, two ways", :unknown),
          row("zeros", "Where the axes started counting", "fitted from the stars; home not needed", :good),
          row("signs", "Which way each motor turns", "checked", :good),
          row("points", "What the alignment rests on", "#{m.n} points, ±#{round(margin)}′", if(margin < a.field / 2, do: :good, else: :bad))
        ]
    end
  end

  defp rows(2, a) do
    value = if m = model(a), do: "not used: would miss by #{deg1(m.off_pole)}", else: "not used: needs home set on a polar-aligned mount"
    [row("perfect", "If the mount were perfect", value, :off)]
  end

  defp rows(1, a) do
    [
      row("view", "Which way is which in the eyepiece", "down is #{view_axis(a.view_map, "down")}, right is #{view_axis(a.view_map, "right")}", :good),
      row("field", "How much sky the eyepiece shows", "#{a.field}′", :good)
    ]
  end

  defp rows(0, a) do
    case a.snap do
      %{axes: %{ra: ra, dec: dec}} = s ->
        [row("ra", "RA, the tracking axis", axis_words(ra, s.tracking), :good), row("dec", "Dec, the other axis", axis_words(dec, nil), :good)]

      _ ->
        [row("ra", "The mount", "not connected", :bad)]
    end
  end

  defp row(key, label, value, tone), do: %{key: key, label: label, value: value, tone: tone}

  # the state of a row as a mark, so it never rests on colour alone
  defp mark(:good), do: "✓"
  defp mark(:caution), do: "!"
  defp mark(:bad), do: "×"
  defp mark(:unknown), do: "?"
  defp mark(_), do: "–"

  defp target_name(e), do: (e[:target] || %{})[:name] || "the spot a hand left"

  # a hand's input, shown under the layer it drives
  defp input_line(1, a), do: (e = a.events[1]) && "Last from #{e.source}: #{input_words(e)}"
  defp input_line(0, a), do: (e = a.events[0]) && "Last from #{e.source}: #{rates_words(e[:rates])}"
  defp input_line(3, a), do: (e = a.events[3]) && "Last Go To: #{target_name(e)}, #{e[:action] || "sent"}"
  defp input_line(_, _), do: nil

  # -- render ------------------------------------------------------------------------------------

  @impl true
  def render(%{term: term} = assigns) when is_binary(term) do
    all = for {law, _, _} <- Stack.layers(:gem), r <- rows(law, assigns), do: r
    assigns = assign(assigns, t: Terms.get(term), r: Enum.find(all, &(&1.key == term)), detail: detail(term, assigns))

    ~H"""
    <.page id="stack-term" night={@night}>
      <:header>
        <.back patch={~p"/stack/#{@selected}"} label="Control Stack" />
        <.title>{(@t && @t.name) || @term}</.title>
        <.actions><.stop click="estop" /></.actions>
      </:header>

      <p :if={@r} class={["stack-big", "tone-#{@r.tone}"]} role="status"><span aria-hidden="true">{mark(@r.tone)} </span>{@r.value}</p>
      <.kv :for={{k, v} <- @detail} label={k} value={v} />

      <section :if={@t} class="stack-explain">
        <h2>What It Is</h2>
        <p>{@t.what}</p>
        <h2>Where the Number Comes From</h2>
        <p>{@t.source}</p>
        <h2 :if={@t.fix != ""}>What You Can Do</h2>
        <p :if={@t.fix != ""}>{@t.fix}</p>
      </section>
      <p class="fine"><.link href={~p"/docs/stack"} class="help">The control stack, in the docs</.link></p>
    </.page>
    """
  end

  def render(assigns) do
    assigns = assign(assigns, working: working(assigns), layers: Stack.layers(:gem))

    ~H"""
    <.page id="stack" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Controls", @selected)} />
        <.title>Control Stack</.title>
        <%!-- the Controls section's status: what the mount is doing and where it points --%>
        <.status label="Mount">{live_render(@socket, Controller.ControlsStatusLive, id: "controls-status", session: %{"id" => @selected})}</.status>
        <.actions><.help href={~p"/docs/stack"} label="the control stack" /><.stop click="estop" /></.actions>
      </:header>

      <p class="stack-now" role="status">{now_words(assigns)}</p>

      <section :for={{law, name, what} <- @layers} class={["stack-layer", law in @working && "working"]} aria-labelledby={"layer-#{law}"}>
        <div class="stack-head">
          <h2 id={"layer-#{law}"}>{name}</h2>
          <span :if={law in @working} class="stack-chip">working now</span>
        </div>
        <p class="stack-what">{what}</p>
        <ul class="stack-rows" role="list">
          <li :for={r <- rows(law, assigns)}>
            <.link patch={~p"/stack/#{@selected}/#{r.key}"} class="stack-row">
              <span class="stack-label">{r.label}</span>
              <span class={["stack-value", "tone-#{r.tone}"]}><span aria-hidden="true">{mark(r.tone)} </span>{r.value}</span>
              <span class="stack-go" aria-hidden="true">›</span>
            </.link>
          </li>
        </ul>
        <p :if={line = input_line(law, assigns)} class="stack-input">{line}</p>
      </section>

      <%!-- the mark carries the state, so it survives night mode, where every tone is red --%>
      <p class="fine">Layers for a German equatorial mount{if @selected, do: ", #{@selected}"}. ✓ working well, ! works with a caveat, × needs a fix, ? not measured yet, – not in use. <.link href={~p"/docs/stack"} class="help">How to read this</.link></p>
    </.page>
    """
  end

  # the drill-down's live numbers, per term
  defp detail("tripod", _a), do: [{"North–south", "unknown"}, {"East–west", "unknown"}, {"Splits it", "a level reading of the mount head"}]

  defp detail("polar", a) do
    case model(a) do
      nil -> []
      m -> [{"Below the pole", deg2(m.axis_low)}, {"West of it", deg2(m.axis_west)}, {"In all", deg2(m.off_pole)}]
    end
  end

  defp detail("points", a) do
    case model(a) do
      nil -> []
      m -> [{"Points", "#{m.n}"}, {"They agree to", "#{arcmin(m.rms)} rms"}, {"Margin (twice that)", "±#{round(2 * m.rms)}′"}, {"Eyepiece field", "#{a.field}′"}]
    end
  end

  defp detail("zeros", a) do
    case model(a) do
      nil -> []
      m -> [{"RA axis", "#{deg2(m.off_ra)} from its start"}, {"Dec axis", "#{deg2(m.off_dec)} from its start"}]
    end
  end

  defp detail("hold", a) do
    case {holding(a), live_error(a)} do
      {nil, _} ->
        []

      {e, err} ->
        [{"Target", target_name(e)}] ++
          if(err, do: [{"Off now, RA", arcmin(elem(err, 0))}, {"Off now, Dec", arcmin(elem(err, 1))}], else: []) ++
          [{"Corrects when", "more than 0.5′ off, checking every 20 s"}, {"Last check", action_words(e[:action])}]
    end
  end

  defp detail(k, a) when k in ["ra", "dec"] do
    case a.snap do
      %{axes: axes} = s ->
        ax = axes[String.to_existing_atom(k)]

        [{"Angle", "#{:erlang.float_to_binary(ax.degrees / 1, decimals: 4)}°"}, {"Steps", "#{ax[:steps]}"}, {"Speed", speed_words(ax)}] ++
          if(k == "ra", do: [{"Tracking", tracking_words(s.tracking)}], else: [])

      _ ->
        []
    end
  end

  defp detail(_, _), do: []

  # -- words -------------------------------------------------------------------------------------

  defp now_words(a) do
    cond do
      e = driving(a) -> "#{String.capitalize(e.source)} is driving: #{input_words(e)}"
      e = holding(a) -> "Tracking #{target_name(e)}#{off_now(live_error(a))}"
      e = a.events[5] -> "Tracking stopped #{ago(e, a.now)}"
      a.snap && a.snap[:tracking] not in [nil, :off] -> "Nobody is driving. Sidereal tracking is on."
      true -> "Nobody is driving. The mount is still."
    end
  end

  defp off_now({dr, dd}), do: ", #{arcmin(max(abs(dr), abs(dd)))} off now"
  defp off_now(_), do: ""

  defp ago(e, now) do
    case age(e, now) do
      nil -> ""
      s when s < 90 -> "#{s} s ago"
      s -> "#{div(s, 60)} min ago"
    end
  end

  defp action_words(:hold), do: "close enough, left alone"
  defp action_words({:corrected, axes}), do: "corrected #{Enum.map_join(axes, " and ", &axis_name/1)}"
  defp action_words(:hand), do: "a hand moved it: tracking the new spot"
  defp action_words(other) when is_binary(other), do: other
  defp action_words(_), do: "running"

  defp axis_name(:ra), do: "RA"
  defp axis_name(:dec), do: "Dec"
  defp axis_name(a), do: to_string(a)

  defp view_axis(map, pair) do
    case map[pair] do
      [axis, s] -> "#{axis_name(String.to_existing_atom(axis))} #{if s > 0, do: "+", else: "−"}"
      _ -> "unknown"
    end
  end

  defp input_words(%{view: {x, y}, speed: v} = e) do
    way = [if(y > 0.38, do: "up"), if(y < -0.38, do: "down"), if(x > 0.38, do: "right"), if(x < -0.38, do: "left")] |> Enum.reject(&is_nil/1) |> Enum.join(" and ")
    "view #{if way == "", do: "still", else: way} at #{rate(v)} → #{rates_words(e[:rates])}"
  end

  defp input_words(e), do: rates_words(e[:rates])

  defp rates_words(nil), do: "let go"
  defp rates_words([]), do: "let go"
  defp rates_words(rates), do: Enum.map_join(rates, ", ", fn {a, r} -> "#{axis_name(a)} #{if r >= 0, do: "+", else: "−"}#{rate(abs(r))}" end)

  defp axis_words(ax, tracking) do
    cond do
      ax.running and tracking not in [nil, :off] and abs(abs(ax[:deg_per_s] || 0) / @sidereal - 1) < 0.1 -> "tracking at 1×"
      ax.running -> speed_words(ax)
      true -> "still"
    end
  end

  defp speed_words(ax) do
    if ax.running do
      "#{rate(abs(ax[:deg_per_s] || 0.0) / @sidereal)} #{if ax[:direction] == :reverse, do: "back", else: "forward"}#{if ax[:mode] == :goto, do: ", Go To", else: ""}"
    else
      "still"
    end
  end

  defp tracking_words(mode) when mode in [nil, :off], do: "off"
  defp tracking_words(mode), do: "#{mode}, the RA motor"

  defp rate(v) when v < 10, do: "#{:erlang.float_to_binary(v / 1, decimals: 1)}×"
  defp rate(v), do: "#{round(v)}×"

  defp arcmin(v), do: "#{:erlang.float_to_binary(abs(v) / 1, decimals: 1)}′"
  defp deg1(v), do: "#{:erlang.float_to_binary(v / 1, decimals: 1)}°"
  defp deg2(v), do: "#{:erlang.float_to_binary(v / 1, decimals: 2)}°"
end
