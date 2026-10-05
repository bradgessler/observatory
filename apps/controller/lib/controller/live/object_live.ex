defmodule Controller.ObjectLive do
  @moduledoc """
  One object: what it is, where it is right now, whether this telescope will
  show it, and the buttons that matter: Go To, Spiral Search, Centered.

  Above the buttons, three answers (`Controller.Sky.Reach`): can you look at
  it, will Go To put it in the eyepiece, how long will tracking keep it. A Go
  To that needs a meridian flip asks first and goes in two legs
  (`Controller.Sky.Moves`), stopping at the home position to ask whether the
  way is clear.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  alias Controller.Sky.{
    Astro,
    Blurbs,
    Catalog,
    Ephemeris,
    Lineup,
    Moves,
    Pointing,
    Reach,
    Tracker
  }

  @spiral_pause_ms 2_500

  @impl true
  def mount(%{"id" => id} = params, session, socket) do
    now = DateTime.utc_now()
    obj = Catalog.object(id) || Enum.find(Ephemeris.objects(now, Pointing.site()), &(&1.id == id))

    if connected?(socket) do
      send(self(), :rescan)
      :timer.send_interval(15_000, :tick)
      Settings.subscribe()
      Telescope.subscribe("moves")
      Telescope.subscribe("tracker")
      Telescope.subscribe("center")
    end

    {:ok,
     socket
     |> assign(
       id: id,
       obj: obj,
       now: now,
       refs: %{},
       snap: nil,
       selected: params["mount"] || session["telescope"],
       # where the back link goes: the list or page that opened this one
       from: params["from"],
       notice: nil,
       page_title: if(obj, do: obj.name, else: "Not in the catalog"),
       search: nil,
       night: Settings.get("night", false),
       aperture: Settings.get("aperture_mm", 100),
       confirming: false,
       can_undo: false,
       flip_ask: nil,
       move: nil,
       holding: nil,
       utc_offset_min: nil,
       # the chart this viewer picked on the Sky Map, for its path across the sky
       view: Controller.Viewer.get(session["viewer"], :sky_view, "dome")
     )
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:tick, socket),
    do: {:noreply, socket |> assign(now: DateTime.utc_now()) |> compute()}

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}

  def handle_info({:settings, _key, _v}, socket),
    do: {:noreply, socket |> assign(aperture: Settings.get("aperture_mm", 100)) |> compute()}

  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected,
      do: {:noreply, assign(socket, snap: snap)},
      else: {:noreply, socket}
  end

  # Centered from the pad or the Center page: say what it recorded, with Undo
  def handle_info({:centered_point, id, what}, socket) do
    if id == socket.assigns.selected do
      notice =
        case what do
          {:unknown, _} -> "Centered, but on what? Nothing is being tracked. Tap Centered on the object's own page."
          %{name: name, n: n, rms_arcmin: rms} -> "Centered on #{name} from the game controller: #{n} alignment point#{if n == 1, do: "", else: "s"}#{if n >= 3 and rms, do: ", agreeing to #{fmt1(rms)}′", else: ""}"
        end

      {:noreply, socket |> assign(notice: notice, can_undo: is_map(what)) |> compute()}
    else
      {:noreply, socket}
    end
  end

  def handle_info({:centered, _}, socket), do: {:noreply, socket}

  def handle_info({:move, id, move}, socket) do
    if id == socket.assigns.selected,
      do: {:noreply, assign(socket, move: move)},
      else: {:noreply, socket}
  end

  # the hold started or ended: the Track answer changes; its every tick doesn't
  def handle_info({:tracker, id, status}, socket) do
    name = status && status.name

    if id == socket.assigns.selected and name != socket.assigns.holding,
      do: {:noreply, socket |> assign(holding: name) |> compute()},
      else: {:noreply, socket}
  end

  def handle_info(:search_step, %{assigns: %{search: nil}} = socket), do: {:noreply, socket}

  def handle_info(
        :search_step,
        %{assigns: %{search: %{steps: steps, n: n} = search, snap: snap}} = socket
      ) do
    stopped? =
      is_map(snap) and is_integer(snap[:estop_at]) and
        snap.estop_at > Map.get(search, :started, 0)

    case if stopped?, do: :stopped, else: Enum.at(steps, n) do
      :stopped ->
        {:noreply, assign(socket, search: nil, notice: "Spiral Search stopped")}

      nil ->
        {:noreply, assign(socket, search: nil, notice: "Searched every view out to three times the margin without it. Go To again, or center anything you can name and tap Centered to tighten the alignment.")}

      {dra, ddec} ->
        ref = socket.assigns.refs[socket.assigns.selected]
        safe(fn -> if dra != 0, do: Mount.goto_relative(ref, :ra, dra * search.ra_step) end)
        safe(fn -> if ddec != 0, do: Mount.goto_relative(ref, :dec, ddec * search.step) end)
        Process.send_after(self(), :search_step, @spiral_pause_ms)
        {:noreply, assign(socket, search: %{search | n: n + 1})}
    end
  end

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)

    selected =
      if socket.assigns.selected in Map.keys(refs),
        do: socket.assigns.selected,
        else: refs |> Map.keys() |> Mount.default()

    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)

    assign(socket,
      refs: refs,
      selected: selected,
      snap: if(is_map(snap), do: snap),
      move: selected && Moves.pending(selected)
    )
  end

  # Where it is now and whether it's on tonight's list (which carries the plain-words verdict).
  defp compute(%{assigns: %{obj: nil}} = socket), do: socket

  defp compute(socket) do
    %{obj: obj, now: now} = socket.assigns
    ctx = Pointing.context(now, socket.assigns.selected)
    lst = Astro.lst_deg(now, ctx.site.lon)
    {alt, az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, ctx.site.lat, lst)
    horizon = Settings.horizon()
    # no tree line given: the real horizon, not an invented one
    tree = if Settings.get("horizon"), do: Settings.horizon_at(horizon, az), else: 0
    ranked = Controller.SkyLive.targets(now, ctx.site, horizon, socket.assigns.aperture)
    entry = Enum.find(ranked, &(&1.id == obj.id))
    rank = entry && Enum.find_index(ranked, &(&1.id == obj.id)) + 1

    id = socket.assigns.selected
    off = socket.assigns.utc_offset_min

    reach =
      Reach.of(obj, socket.assigns.snap, ctx,
        horizon: horizon,
        trees?: Settings.get("horizon") != nil,
        field: Settings.get("eyepiece_field_arcmin", 72),
        lock: id && Lineup.status(id),
        tracker: id && Tracker.status(id),
        ended: id && Tracker.ended(id),
        clock: &clock(&1, off)
      )

    trees? = Settings.get("horizon") != nil

    assign(socket,
      ctx: ctx,
      # its night: the sky now with its path across it, and its altitude dusk to dawn
      scene: Controller.Sky.Scene.build(now, ctx.site, horizon, view: socket.assigns.view, trees: trees?, sky: false),
      site: ctx.site,
      horizon: if(trees?, do: horizon),
      alt: alt,
      az: az,
      tree: tree,
      entry: entry,
      rank: rank,
      visible: alt > tree,
      scope: Pointing.scope_radec(socket.assigns.snap, ctx),
      reach: reach,
      holding: id && (Tracker.status(id) || %{})[:name]
    )
  end

  defp clock(t, nil), do: Calendar.strftime(t, "%H:%M") <> " UTC"
  defp clock(t, off), do: Calendar.strftime(DateTime.add(t, off * 60, :second), "%H:%M")

  # -- events -----------------------------------------------------------------------

  @impl true
  def handle_event("clock", %{"offset_min" => off}, socket) when is_integer(off),
    do: {:noreply, socket |> assign(utc_offset_min: off) |> compute()}

  def handle_event("clock", _, socket), do: {:noreply, socket}

  def handle_event("slew", params, %{assigns: %{obj: obj, snap: snap}} = socket) do
    ref = socket.assigns.refs[socket.assigns.selected]
    watched = params["watched"] == "true"
    track = Settings.get("auto_track", true)

    {notice, ask} =
      case Pointing.slew(ref, snap, obj, socket.assigns.ctx, track: track, watched: watched) do
        {:ok, _d_ra, _d_dec} when watched ->
          {"Going to #{obj.name} on this side, with you watching. Tracking stops when the counterweight reaches its limit#{limit_in(socket.assigns.flip_ask)}",
           nil}

        {:ok, d_ra, d_dec} ->
          {"Going to #{obj.name} (RA #{fmt1(d_ra)}°, Dec #{fmt1(d_dec)}°)", nil}

        # the other side of the pier: ask, and offer to stay while there's time
        {:error, {:flip, info}} ->
          {nil, info}

        {:error, e} ->
          {Pointing.refusal_words(e, obj.name), nil}
      end

    {:noreply, socket |> assign(notice: notice, flip_ask: ask) |> compute()}
  end

  def handle_event("flip", _, %{assigns: %{obj: obj}} = socket) do
    notice =
      case Moves.flip(socket.assigns.selected, obj, track: Settings.get("auto_track", true)) do
        {:ok, :home} -> nil
        {:error, e} -> Pointing.refusal_words(e, obj.name)
      end

    {:noreply,
     assign(socket, flip_ask: nil, notice: notice, move: Moves.pending(socket.assigns.selected))}
  end

  def handle_event("flip_on", _, socket) do
    name = socket.assigns.move && socket.assigns.move.obj.name

    notice =
      case Moves.continue(socket.assigns.selected) do
        {:ok, _, _} -> "Going on to #{name} on the other side of the pier"
        {:error, :nothing_pending} -> nil
        {:error, e} -> Pointing.refusal_words(e, name)
      end

    {:noreply, assign(socket, notice: notice, move: nil)}
  end

  def handle_event("flip_stay", _, socket) do
    Moves.cancel(socket.assigns.selected)

    {:noreply,
     assign(socket, move: nil, notice: "Staying at the home position. Go To again when you're ready")}
  end

  def handle_event("flip_cancel", _, socket), do: {:noreply, assign(socket, flip_ask: nil)}

  def handle_event("stop", _, socket) do
    Moves.cancel(socket.assigns.selected)
    Controller.Sky.Tracker.stop(socket.assigns.selected)
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.stop(ref) end)
    {:noreply, assign(socket, notice: "Stopped", search: nil)}
  end

  # Centered is deliberate: a wrong one pulls every Go To after it off. The
  # first tap asks; the answer records the point; Undo takes it back.
  def handle_event("sync", _, socket),
    do: {:noreply, assign(socket, confirming: true, notice: nil)}

  def handle_event("sync_cancel", _, socket), do: {:noreply, assign(socket, confirming: false)}

  def handle_event("undo", _, socket) do
    id = socket.assigns.selected
    n = length(Controller.Sky.Lineup.samples(id))
    if n > 0, do: Controller.Sky.Lineup.drop(id, n - 1)

    {:noreply,
     socket
     |> assign(
       can_undo: false,
       notice:
         "Took back the last Centered: #{max(n - 1, 0)} alignment point#{if n - 1 == 1, do: "", else: "s"} left"
     )
     |> compute()}
  end

  def handle_event("sync_confirm", _, %{assigns: %{obj: obj, snap: snap}} = socket) do
    socket = assign(socket, confirming: false)

    # "It's in the middle of the eyepiece": an alignment point, zeroed or not
    if snap && snap.connected do
      st = Pointing.sync(snap, obj, socket.assigns.ctx)

      {:noreply,
       socket
       |> assign(
         can_undo: true,
         notice:
           "Centered on #{obj.name}: #{st.n} alignment point#{if st.n == 1, do: "", else: "s"}#{if st.n >= 3 and st.rms_arcmin, do: ", agreeing to #{fmt1(st.rms_arcmin)}′", else: ""}"
       )
       |> compute()}
    else
      {:noreply, assign(socket, notice: "No mount connected")}
    end
  end

  # A widening square around where Go To landed (#100): steps a bit under
  # the eyepiece's field so views overlap, out to three times the alignment's
  # margin. The hold would pull each step back, so it stands down and the
  # mount's own sidereal drive keeps the sky still meanwhile; "I See It" holds
  # wherever the search stopped, as the object.
  def handle_event("search", _, socket) do
    if socket.assigns.search do
      {:noreply, socket}
    else
      id = socket.assigns.selected
      ref = socket.assigns.refs[id]
      field = Settings.get("eyepiece_field_arcmin", 72) / 60
      step = field * 0.7

      margin =
        case id && Lineup.status(id) do
          %{n: n, rms_arcmin: rms} when n >= 3 and is_number(rms) -> 2 * rms / 60
          _ -> 2.0
        end

      rings = (3 * margin / step) |> Float.ceil() |> trunc() |> max(1) |> min(4)
      cos_dec = max(:math.cos(socket.assigns.obj.dec_deg * :math.pi() / 180), 0.3)

      if id && Tracker.active?(id), do: Tracker.stop(id, halt: false)
      if ref, do: safe(fn -> Mount.track(ref, :sidereal) end)
      Process.send_after(self(), :search_step, @spiral_pause_ms)

      {:noreply,
       assign(socket,
         search: %{steps: spiral(rings), n: 0, step: step, ra_step: step / cos_dec, started: System.monotonic_time(:millisecond)},
         notice: nil
       )}
    end
  end

  # found: stop searching, hold right here as the object
  def handle_event("search_found", _, %{assigns: %{obj: obj, snap: snap}} = socket) do
    id = socket.assigns.selected

    case snap && Pointing.scope_radec(snap, socket.assigns.ctx) do
      {ra, dec} ->
        Tracker.track(id, %{name: obj.name, ra_deg: ra, dec_deg: dec}, obj)
        {:noreply, assign(socket, search: nil, notice: "Tracking #{obj.name} where you found it. Center it and tap Centered to make the next Go To land closer.")}

      _ ->
        {:noreply, assign(socket, search: nil, notice: "Spiral Search stopped")}
    end
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  # unit moves of a square spiral covering `rings` rings: 8, 24, 48, 80 views
  defp spiral(rings) do
    dirs = [{1, 0}, {0, 1}, {-1, 0}, {0, -1}]

    Stream.iterate({0, 1}, fn {i, len} -> {i + 1, if(rem(i, 2) == 1, do: len + 1, else: len)} end)
    |> Stream.flat_map(fn {i, len} -> List.duplicate(Enum.at(dirs, rem(i, 4)), len) end)
    |> Enum.take((2 * rings + 1) * (2 * rings + 1) - 1)
  end

  # minutes until tracking carries the counterweight to the hard limit, 15° an hour
  defp limit_in(%{past: past}) when is_number(past),
    do: ", about #{round((Pointing.meridian_hard() - past) / 15.04 * 60)} min"

  defp limit_in(_), do: ""

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end

  # -- render -------------------------------------------------------------------------

  # The back link names the page that opened this one, when it said so.
  defp back_to("tonight", id), do: {"Tonight", if(id, do: ~p"/tonight/#{id}", else: ~p"/tonight")}
  defp back_to("start", id), do: {"Status", if(id, do: ~p"/alignment/#{id}", else: ~p"/alignment")}
  defp back_to(_, id), do: {"Sky Map", if(id, do: ~p"/sky/#{id}", else: ~p"/sky")}

  @impl true
  def render(%{obj: nil} = assigns) do
    ~H"""
    <main class={["object", @night && "night"]}>
      <header class="page-header">
        <.back navigate={elem(back_to(@from, @selected), 1)} label={elem(back_to(@from, @selected), 0)} />
        <.title>Not in the Catalog</.title>
        <.actions><.stop /></.actions>
      </header>
      <.skip_target />
      <p class="empty">Nothing called "{@id}" in the catalog.</p>
    </main>
    """
  end

  def render(assigns) do
    # the name alone up top; a qualifier ("Moon · last quarter") goes on the card
    [name | about] = String.split(assigns.obj.name, " · ", parts: 2)
    {back_label, back_path} = back_to(assigns.from, assigns.selected)
    assigns = assign(assigns, name: name, about: List.first(about), back_label: back_label, back_path: back_path)

    ~H"""
    <main class={["object", @night && "night"]}>
      <header class="page-header">
        <.back navigate={@back_path} label={@back_label} />
        <.title>{@name}</.title>
        <.actions>
          <.help href={~p"/docs/sky#go-to"} label="Go To, tracking and Centered" />
          <.stop />
        </.actions>
      </header>
      <.skip_target />

      <.split class="object-split">
        <:main>
          <Controller.Components.NightPath.figure id="object-path" scene={@scene} obj={@obj} utc_offset_min={@utc_offset_min} />
          <Controller.Components.Visibility.plot targets={[@obj]} site={@site} at={@now} utc_offset_min={@utc_offset_min} horizon={@horizon} />
        </:main>
        <:side>
          <section class="card">
            <p class="kind">
              {kind_name(@obj.kind)}<span :if={@about}> · {@about}</span><span :if={@obj[:desig]}> · {@obj.desig}</span><span :if={@rank}>
                 · #{@rank} tonight
              </span>
            </p>
            <p class="blurb">{Blurbs.for(@obj)}</p>
          </section>

          <dl class="card facts">
            <div>
              <dt class="k">now</dt>
              <dd class="v">
                {if @alt > 0, do: "#{fmt0(@alt)}° up, #{compass(@az)}", else: "below the horizon"}
              </dd>
            </div>
            <div>
              <dt class="k">you'll see</dt>
              <dd class="v">{verdict(assigns)}</dd>
            </div>
            <div :if={@entry}>
              <dt class="k">window</dt>
              <dd class="v">{when_text(@entry.status)}</dd>
            </div>
            <div>
              <dt class="k">brightness</dt>
              <dd class="v">mag {@obj.mag} <.help href={~p"/docs/magnitude"} label="magnitude" /></dd>
            </div>
          </dl>

          <section class="actions">
            <.link
              navigate={
                if @selected,
                  do: ~p"/sky/#{@selected}?#{[pick: @obj.id]}",
                  else: ~p"/sky?#{[pick: @obj.id]}"
              }
              class="btn big"
            >
              Show on Sky Map
            </.link>
            <ul class="reach" role="list" aria-label={"#{@obj.name}: look, Go To, track"}>
              <li
                :for={
                  {label, c} <- [{"Look", @reach.look}, {"Go To", @reach.go}, {"Track", @reach.track}]
                }
                class={"tone-#{c.tone}"}
              >
                <span class="reach-mark" aria-hidden="true">{c.mark}</span>
                <span class="reach-t"><strong>{label}</strong><span>{c.text}</span></span>
              </li>
            </ul>
            <p :if={@snap && @snap[:stalled]} class="stall-line tone-bad" role="status">
              {stall_words(@snap.stalled, @utc_offset_min)}
            </p>
            <button
              class="go big"
              phx-click="slew"
              disabled={!@snap || !@snap.connected}
              aria-label={"Go to #{@obj.name}"}
            >
              Go To
            </button>
            <div class="row">
              <button
                :if={!@search}
                phx-click="search"
                disabled={!@snap || !@snap.connected}
                aria-label={"Spiral search: sweep around #{@obj.name} in a widening square until you see it"}
              >
                Spiral Search
              </button>
              <button :if={@search} class="go" phx-click="search_found">I See It</button>
              <button
                phx-click="sync"
                disabled={!@snap || !@snap.connected}
                aria-label={"Centered: #{@obj.name} is in the middle of the eyepiece; adds an alignment point"}
              >
                Centered
              </button>
            </div>
            <button id="object-awake" type="button" class="btn" phx-hook="Awake" phx-update="ignore" aria-pressed="false">Keep Screen On</button>
            <p :if={@search} class="move-line" role="status">
              Spiral Search: view {@search.n} of {length(@search.steps)}, {round(@search.step * 60)}′ apart. Tap I See It when it's in the eyepiece; STOP ends it.
            </p>
            <p class="hint">
              Spiral Search sweeps around it until you see it. Centered, when it's in the middle, makes the next Go To land closer.
            </p>
            <section :if={@confirming} class="card confirm" role="alertdialog" aria-labelledby="confirm-q">
              <p id="confirm-q"><strong>Is {@obj.name} in the middle of the eyepiece?</strong></p>
              <p class="hint">
                Center it first with the touchpad or the D-pad. A wrong Centered pulls every Go To after it off; you can undo it.
              </p>
              <div class="row">
                <button class="go" phx-click="sync_confirm">Yes, It's Centered</button>
                <button phx-click="sync_cancel">Cancel</button>
              </div>
            </section>
            <button :if={@can_undo} phx-click="undo">Undo That Centered</button>
            <section :if={@flip_ask} class="card confirm" role="alertdialog" aria-labelledby="flip-q">
              <p id="flip-q"><strong>{@obj.name} is on the other side of the meridian.</strong></p>
              <p class="hint">
                From this side the counterweight would sit {round(@flip_ask.past)}° above level. Go To flips the mount to the other side of the pier in two legs: first to the home position (counterweight down, tube at the pole), where it stops so you can check the way is clear, then on to {@obj.name}.
              </p>
              <div class="row">
                <button class="go" phx-click="flip">Flip, in Two Legs</button>
                <button
                  :if={@flip_ask.stay? and @flip_ask.past < Pointing.meridian_hard() - 2}
                  phx-click="slew"
                  phx-value-watched="true"
                >
                  Stay This Side{limit_in(@flip_ask)}
                </button>
                <button phx-click="flip_cancel">Cancel</button>
              </div>
            </section>
            <p :if={@move && @move.leg == :home} class="move-line" role="status">
              Leg 1 of 2: going to the home position (counterweight down, tube at the pole). It stops there and asks before going on to {@move.obj.name}.
            </p>
            <section
              :if={@move && @move.leg == :waiting}
              class="card confirm"
              role="alertdialog"
              aria-labelledby="leg-q"
            >
              <p id="leg-q"><strong>At the home position, halfway to {@move.obj.name}. Is the way clear?</strong></p>
              <p class="hint">
                The next leg swings the tube down to {@move.obj.name} on the other side of the pier. Look at the legs and the cables on that side, then go on. STOP works all the way.
              </p>
              <div class="row">
                <button class="go" phx-click="flip_on">Continue to {@move.obj.name}</button>
                <button phx-click="flip_stay">Stay Here</button>
              </div>
            </section>
            <p :if={!@snap} class="horizon-hint">No mount connected.</p>
          </section>
        </:side>
      </.split>

      <.notice notice={@notice} />
      <div id="object-clock" phx-hook="Clock" hidden></div>
    </main>
    """
  end

  defp stall_words(%{axis: axis, at: at}, off) do
    t = DateTime.from_unix!(at, :millisecond)

    "#{if axis == :ra, do: "RA", else: "Dec"} stopped counting while told to move at #{clock(t, off)}, so both axes stopped. Check the mount's power and cable, then Go To again."
  end

  defp verdict(%{visible: false, alt: alt, tree: tree}) when alt > 0,
    do: "Behind your tree line (#{fmt0(alt)}° up, trees to #{tree}°)"

  defp verdict(%{visible: false}), do: "Not up right now"
  defp verdict(%{entry: %{words: w}}), do: w
  defp verdict(_), do: "Faint for this telescope tonight"

  defp kind_name(:moon), do: "The Moon"
  defp kind_name(:planet), do: "Planet"
  defp kind_name(:star), do: "Star"
  defp kind_name(:cluster), do: "Star cluster"
  defp kind_name(:galaxy), do: "Galaxy"
  defp kind_name(:nebula), do: "Nebula"
  defp kind_name(:planetary), do: "Planetary nebula"
  defp kind_name(k), do: to_string(k)

  defp when_text(:good), do: "Up for 2h+"
  defp when_text(:sets_later), do: "Sets within 2h"
  defp when_text(:sets_soon), do: "Sets within the hour, look now"
  defp when_text(:rising), do: "Rises within 2h"

  defp compass(az), do: Enum.at(~w(N NE E SE S SW W NW), round(Astro.norm360(az) / 45) |> rem(8))
  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)
end
