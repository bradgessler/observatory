defmodule Controller.SkyLive do
  @moduledoc """
  The sky from where you're standing, right now: stars to mag 5, Messier and
  named DSOs, constellation lines, and your local tree line shaded out. Tap
  anything and the selected mount slews to it. "Tonight" ranks what you can
  actually see over the next couple of hours from this spot.

  Pointing is a first-order model and says so in the UI: home at the pole
  with the counterweight down, axis signs from `config :controller, :pointing`.
  """
  use Controller, :live_view
  import Controller.Components.UI
  import Controller.Components.SkyChart
  alias Controller.Components.{SkyChart, SkyStatus}

  alias Controller.Settings

  alias Controller.Sky.{
    Astro,
    Catalog,
    Ephemeris,
    Lineup,
    Pointing,
    Reach,
    Scene,
    Tracker
  }

  @tick_ms 15_000
  # Search spiral: one low-power eyepiece field per step, a pause to look.
  @spiral_step 0.4
  @spiral_pause_ms 2_500
  # Crowd-pleasers, by experience rather than magnitude: things that make people say "whoa".
  @showpieces ~w(m13 m57 m27 m31 m42 m45 m11 m22 m8 m17 m16 m20 m51 m81 m82 m104 m92 m44 m35 m3 m5 m15 m2 m4 m6 m7 m1 m33)
  @showpiece_stars ~w(Albireo Mizar Polaris Antares Betelgeuse Rigel Sirius Capella Aldebaran Arcturus Vega)

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      :timer.send_interval(@tick_ms, :tick)
      Settings.subscribe()
    end

    # nested inside another page (live_render), the mount id arrives in the session
    # (and params is :not_mounted_at_router, not a map)
    params = if(is_map(params), do: params, else: %{}) |> Map.put_new("id", session["id"])

    {:ok,
     socket
     |> assign(
       site: site_setting(),
       pointing: pointing_setting(),
       # After a slew from this page, start sidereal tracking so the target stays put.
       auto_track: Settings.get("auto_track", true),
       horizon: Settings.horizon(),
       # One-star sync: degrees added to the model's axis targets. Persisted.
       offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0}),
       search: nil,
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       # Aperture of the scope in use, mm. 0 = naked eye. Drives limiting magnitude.
       aperture: Settings.get("aperture_mm", 100),
       # Photo → obstructions: boundary traced in the browser, solve runs in a Task.
       now: DateTime.utc_now(),
       refs: %{},
       snap: nil,
       selected: params["id"],
       target: nil,
       notice: nil,
       page_title: if(socket.assigns[:live_action] == :tonight, do: "Tonight", else: "Sky Map"),
       # the viewer's offset from UTC, from their browser (the Clock hook); nil until it says
       utc_offset_min: nil,
       # minutes ahead of (or behind) now that this viewer is looking at the sky, and
       # the chart they picked: theirs (Controller.Viewer), kept from page to page
       viewer: session["viewer"],
       shift_min: Controller.Viewer.get(session["viewer"], :sky_shift, 0),
       view: Controller.Viewer.get(session["viewer"], :sky_view, "dome"),
       # Tonight is its own page (the list); the Sky map page is the map and the horizon
       tab: if(socket.assigns[:live_action] == :tonight, do: "targets", else: "map")
     )
     |> rescan()
     |> compute()
     |> pick(params["pick"])}
  end

  # the sky at the time this viewer is looking at: now, or an hour or two either side
  defp sky_time(%{now: now, shift_min: shift}), do: DateTime.add(now, shift * 60, :second)

  defp pick(socket, nil), do: socket

  defp pick(socket, id) do
    socket
    |> assign(target: Catalog.object(id) || Enum.find(Ephemeris.objects(socket.assigns.now, socket.assigns.site), &(&1.id == id)))
    |> night_path()
  end

  # No handle_params: this view can be nested inside another page (child views may
  # not define it). Mount and rescan pick the mount.

  # -- live updates ---------------------------------------------------------------------

  @impl true
  def handle_info(:tick, socket),
    do: {:noreply, socket |> assign(now: DateTime.utc_now()) |> compute()}

  # A setting changed on some phone: reload what this page derives from settings.
  def handle_info({:settings, _key, _v}, socket) do
    {:noreply,
     socket
     |> assign(
       site: site_setting(),
       pointing: pointing_setting(),
       offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0}),
       horizon: Settings.horizon(),
       aperture: Settings.get("aperture_mm", 100),
       auto_track: Settings.get("auto_track", true),
       night: Settings.get("night", false)
     )
     |> compute()}
  end

  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected,
      do: {:noreply, assign(socket, snap: snap)},
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
        {:noreply,
         assign(socket,
           search: nil,
           notice: "Spiral Search finished without it. Try a wider eyepiece, or tighten the alignment: center any star and tap Centered"
         )}

      {dra, ddec} ->
        ref = socket.assigns.refs[socket.assigns.selected]

        try do
          if dra != 0, do: Mount.goto_relative(ref, :ra, dra * @spiral_step)
          if ddec != 0, do: Mount.goto_relative(ref, :dec, ddec * @spiral_step)
        catch
          :exit, _ -> :ok
        end

        Process.send_after(self(), :search_step, @spiral_pause_ms)
        {:noreply, assign(socket, search: %{search | n: n + 1})}
    end
  end

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})

    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id) do
      Mount.subscribe(ref)
      # a tracking-direction flip made in the field applies to mounts that appear later, too
      case Settings.get("tracking_direction") do
        d when d in ["forward", "reverse"] ->
          safe(fn -> Mount.configure(ref, tracking_direction: String.to_atom(d)) end)

        _ ->
          :ok
      end
    end

    socket = assign(socket, refs: refs)

    selected =
      if socket.assigns.selected in Map.keys(refs),
        do: socket.assigns.selected,
        else: first_id(socket)

    snap = if ref = refs[selected], do: safe_snapshot(ref)
    assign(socket, selected: selected, snap: snap)
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Mount.default()

  # Config gives the defaults; anything changed from the Horizon tab overrides them.
  defp site_setting,
    do: Controller.Sky.Pointing.site() |> Map.put(:set, Controller.Sky.Pointing.site_set?())

  defp pointing_setting do
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    case Settings.get("pointing") do
      %{"ha_sign" => h, "dec_sign" => d} when h in [-1, 1] and d in [-1, 1] ->
        %{ha_sign: h, dec_sign: d}

      _ ->
        base
    end
  end

  defp flip_pointing(socket, key) do
    p = Map.update!(socket.assigns.pointing, key, &(-&1))
    Settings.put("pointing", %{"ha_sign" => p.ha_sign, "dec_sign" => p.dec_sign})
    # the sync offset was measured under the old signs; it's meaningless now
    Settings.put("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})

    assign(socket,
      pointing: p,
      offset: %{"ra" => 0.0, "dec" => 0.0},
      notice: "#{axis_words(key)} flipped; sync offset cleared. Center a star and tap Centered"
    )
  end

  # the same words the Modes strip uses for a flipped sign
  defp axis_words(:ha_sign), do: "RA axis"
  defp axis_words(:dec_sign), do: "Dec axis"

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> :error
    end
  end


  defp safe_snapshot(ref) do
    try do
      Mount.snapshot(ref)
    catch
      _, _ -> nil
    end
  end

  # -- events ---------------------------------------------------------------------------------

  @impl true
  def handle_event("pick", %{"id" => id}, socket) do
    target =
      Catalog.object(id) ||
        Enum.find(Ephemeris.objects(socket.assigns.now, socket.assigns.site), &(&1.id == id))

    # the Sky Map shows a pick over its chart; Tonight keeps its list and shows it beside
    tab = if socket.assigns.live_action == :tonight, do: socket.assigns.tab, else: "map"
    {:noreply, socket |> assign(target: target, notice: nil, tab: tab) |> night_path()}
  end

  def handle_event("clear", _, socket), do: {:noreply, socket |> assign(target: nil, notice: nil) |> night_path()}

  # step the sky an hour either side of now, up to a day; "now" comes back
  def handle_event("shift", %{"by" => "now"}, socket), do: {:noreply, socket |> set_shift(0) |> compute()}

  def handle_event("shift", %{"by" => by}, socket) do
    case Integer.parse(by) do
      {min, ""} ->
        {:noreply,
         socket
         |> set_shift(max(min(socket.assigns.shift_min + min, 24 * 60), -24 * 60))
         |> compute()}

      _ ->
        {:noreply, socket}
    end
  end

  def handle_event("night", _, socket) do
    night = !socket.assigns.night
    Settings.put("night", night)
    {:noreply, assign(socket, night: night)}
  end


  # the chart: the dome, the horizon, the mount's axes (Projection); this viewer's, remembered
  def handle_event("view", %{"view" => view}, socket) when view in ["dome", "horizon", "mount"] do
    Controller.Viewer.put(socket.assigns.viewer, :sky_view, view)
    {:noreply, socket |> assign(view: view) |> compute()}
  end

  # Field calibration without a rebuild: flip an axis sign if the map slews to the
  # mirror image; flip tracking if a star drifts out faster with tracking on.
  def handle_event("flip", %{"what" => "ra"}, socket),
    do: {:noreply, flip_pointing(socket, :ha_sign)}

  def handle_event("flip", %{"what" => "dec"}, socket),
    do: {:noreply, flip_pointing(socket, :dec_sign)}

  def handle_event("flip", %{"what" => "tracking"}, socket) do
    dir =
      if Settings.get("tracking_direction", "forward") == "forward",
        do: "reverse",
        else: "forward"

    Settings.put("tracking_direction", dir)

    for {_id, ref} <- socket.assigns.refs,
        do: safe(fn -> Mount.configure(ref, tracking_direction: String.to_atom(dir)) end)

    {:noreply, assign(socket, notice: "Tracking direction now #{dir}")}
  end

  def handle_event("auto_track", _, socket) do
    v = !socket.assigns.auto_track
    Settings.put("auto_track", v)
    {:noreply, assign(socket, auto_track: v)}
  end

  # The viewer's clock: only its offset is used here, for local time. (The
  # Location page is the one that may set the box's clock from it.) Everything
  # that carries a time in words is said again in it: a Tonight row's "tracks to"
  # as well, or it reads "13:40 UTC" under an "Until dawn, 06:40" until the next tick.
  def handle_event("clock", %{"offset_min" => off}, socket) when is_integer(off),
    do: {:noreply, socket |> assign(utc_offset_min: off) |> reaches() |> night_path() |> sun()}

  def handle_event("clock", _, socket), do: {:noreply, socket}

  def handle_event("equipment", %{"aperture" => a}, socket) do
    aperture =
      case Integer.parse(a) do
        {n, _} -> n |> max(0) |> min(1_000)
        :error -> socket.assigns.aperture
      end

    Settings.put("aperture_mm", aperture)
    {:noreply, socket |> assign(aperture: aperture) |> compute()}
  end


  def handle_event("goto", _, %{assigns: %{target: t, snap: snap}} = socket) when not is_nil(t) do
    ref = socket.assigns.refs[socket.assigns.selected]

    notice =
      case Pointing.slew(ref, snap, t, ctx(socket.assigns), track: socket.assigns.auto_track) do
        {:ok, d_ra, d_dec} -> "Going to #{t.name} (RA #{fmt1(d_ra)}°, Dec #{fmt1(d_dec)}°)"
        {:error, e} -> Pointing.refusal_words(e, t.name)
      end

    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("goto", _, socket), do: {:noreply, socket}

  def handle_event("stop", _, socket) do
    Controller.Sky.Tracker.stop(socket.assigns.selected)
    if ref = socket.assigns.refs[socket.assigns.selected], do: Mount.stop(ref)
    {:noreply, assign(socket, notice: "Stopped", search: nil)}
  end

  # "The scope is centred on the target right now." One tap is a one-star sync;
  # each further star tightens the alignment (Controller.Sky.Lineup).
  def handle_event("sync", _, %{assigns: %{target: t, snap: snap}} = socket) when not is_nil(t) do
    # "It's in the middle of the eyepiece": an alignment point, zeroed or not
    if snap && snap.connected do
      st = Pointing.sync(snap, t, ctx(socket.assigns))

      {:noreply,
       assign(socket,
         notice:
           "Centered on #{t.name}: #{st.n} point#{if st.n == 1, do: "", else: "s"}#{if st.n >= 3 and st.rms_arcmin, do: ", agreeing to #{fmt1(st.rms_arcmin)}′", else: ""}"
       )}
    else
      {:noreply, assign(socket, notice: "No mount connected")}
    end
  end

  def handle_event("sync", _, socket), do: {:noreply, socket}

  # No finder scope? Walk an expanding square spiral around where the target
  # should be, one eyepiece-field at a time, pausing at each stop. Hit Stop
  # when the star shows up, center it with the keypad, then Sync.
  def handle_event("search", _, %{assigns: %{target: t}} = socket) when not is_nil(t) do
    if socket.assigns.search do
      {:noreply, socket}
    else
      Process.send_after(self(), :search_step, @spiral_pause_ms)

      {:noreply,
       assign(socket,
         search: %{steps: spiral(), n: 0, started: System.monotonic_time(:millisecond)},
         notice: "Spiral Search around #{t.name}… STOP when you see it"
       )}
    end
  end

  def handle_event("search", _, socket), do: {:noreply, socket}

  # Square spiral as {d_ra, d_dec} moves in eyepiece-field units: R, U, L, L, D, D, R, R, R, ...
  defp spiral do
    dirs = [{1, 0}, {0, 1}, {-1, 0}, {0, -1}]

    Stream.iterate({0, 1}, fn {i, len} -> {i + 1, if(rem(i, 2) == 1, do: len + 1, else: len)} end)
    |> Stream.flat_map(fn {i, len} -> List.duplicate(Enum.at(dirs, rem(i, 4)), len) end)
    |> Enum.take(48)
  end

  # -- pointing model: see Controller.Sky.Pointing (first-order or lined-up) ---------------------

  defp ctx(assigns), do: Pointing.context(assigns.now, assigns.selected)

  defp scope_radec(snap, assigns), do: Pointing.scope_radec(snap, ctx(assigns))

  # the time this viewer looks at the sky, kept for them across Sky Map and Tonight
  defp set_shift(socket, min) do
    Controller.Viewer.put(socket.assigns.viewer, :sky_shift, min)
    assign(socket, shift_min: min)
  end

  # -- sky computation (once per tick, not per render) ----------------------------------------------

  defp compute(socket) do
    %{site: site, horizon: horizon} = socket.assigns
    now = sky_time(socket.assigns)
    lst = Astro.lst_deg(now, site.lon)
    # no tree line given: the whole sky down to the real horizon, nothing dimmed
    trees? = Settings.get("horizon") != nil

    # the chart: everything where it lands in the projection this viewer picked
    scene = Scene.build(now, site, horizon, view: socket.assigns.view, trees: trees?)
    %{stars: stars, dsos: dsos} = scene
    aperture = socket.assigns.aperture

    assign(socket,
      at: now,
      lst: lst,
      trees: trees?,
      scene: scene,
      stars: stars,
      dsos: dsos,
      modes: Controller.Modes.active(),
      lineup: socket.assigns.selected && Lineup.status(socket.assigns.selected),
      lim: limiting_mag(aperture),
      moon: moon_state(now, site, lst),
      # ranked against the real horizon until a tree line is given
      targets:
        targets(
          now,
          site,
          if(trees?, do: horizon, else: Map.new(Settings.sectors(), &{&1, 0})),
          aperture
        )
    )
    |> reaches()
    |> night_path()
    |> sun()
  end

  # how dark the sky is at the time shown, and the solar graph: the Sky toolbar's middle
  defp sun(socket), do: assign(socket, sun: SkyStatus.sun_info(socket.assigns.at, socket.assigns.site, socket.assigns.utc_offset_min))

  # the picked object's night on the Sky Map's chart: worked out when the sky, the pick or the
  # viewer's clock changes, never on the many renders between (a mount reports four times a second)
  defp night_path(%{assigns: %{target: %{} = t, live_action: action, scene: scene}} = socket) when action != :tonight,
    do: assign(socket, path: Scene.night_path(scene, t.ra_deg, t.dec_deg, socket.assigns.utc_offset_min))

  defp night_path(socket), do: assign(socket, path: nil)

  # Tonight, with a mount to drive: what Go To and the hold will do for each
  # row (Reach, the same answers as an object's page). Without a lock every
  # row would say so; the page says it once instead.
  defp reaches(
         %{assigns: %{live_action: :tonight, snap: %{connected: true} = snap, selected: id}} =
           socket
       ) do
    ctx = Pointing.context(socket.assigns.now, id)

    if snap.homed or Pointing.lined_up?(ctx) do
      off = socket.assigns.utc_offset_min

      opts = [
        horizon: socket.assigns.horizon,
        trees?: socket.assigns.trees,
        field: Settings.get("eyepiece_field_arcmin", 72),
        lock: socket.assigns.lineup,
        tracker: Tracker.status(id),
        ended: Tracker.ended(id),
        clock: &hm(&1, off)
      ]

      reach =
        for o <- socket.assigns.targets,
            o.up,
            into: %{},
            do: {o.id, Reach.of(o, snap, ctx, opts).summary}

      assign(socket, reach: reach, locked: true)
    else
      assign(socket, reach: %{}, locked: false)
    end
  end

  defp reaches(socket), do: assign(socket, reach: %{}, locked: nil)

  # What's worth looking at from this spot, with this scope, over the next two hours.
  # Public: the agent/sky-tour layer (#8, #40) calls this same function.
  def targets(now, site, horizon, aperture_mm) do
    lsts = for h <- [0, 1, 2], do: Astro.lst_deg(DateTime.add(now, h * 3600), site.lon)
    lim = limiting_mag(aperture_mm)
    moon = moon_state(now, site, hd(lsts))

    candidates =
      Ephemeris.objects(now, site) ++
        Catalog.dsos() ++
        Enum.filter(
          Catalog.stars(4.0),
          &(&1.proper != nil and (&1.mag <= 2.6 or &1.proper in @showpiece_stars))
        )

    for o <- candidates,
        o.id != "sol-sun",
        showable?(o, lim, moon),
        [a0, a1, a2] = Enum.map(lsts, &Astro.alt_az(o.ra_deg, o.dec_deg, site.lat, &1)),
        {alt0, az0} = a0,
        tree0 = Settings.horizon_at(horizon, az0),
        # one tuple bind: a bare `up = false` here would act as a filter and drop the row
        {up0, up1, up2} =
          {alt0 > tree0, elem(a1, 0) > Settings.horizon_at(horizon, elem(a1, 1)),
           elem(a2, 0) > Settings.horizon_at(horizon, elem(a2, 1))},
        up0 or up2 do
      status =
        cond do
          up0 and up1 and up2 -> :good
          up0 and not up1 -> :sets_soon
          up0 -> :sets_later
          true -> :rising
        end

      # brighter = better, but a -10 Moon shouldn't get 10 points of it; Messier = curated showpiece
      wow =
        -max(o.mag, -2.0) + kind_bonus(o.kind) + messier_bonus(o) + min(alt0 - tree0, 30) / 30 +
          if(status == :good, do: 1.0, else: 0.0) - if(status == :rising, do: 1.5, else: 0.0) -
          moon_penalty(o, moon)

      Map.merge(o, %{alt: alt0, az: az0, status: status, wow: wow, words: words(o, lim, moon)})
    end
    |> Enum.sort_by(& &1.wow, :desc)
    |> diversify()
    |> Enum.take(30)
    |> windows(now, site, horizon)
  end

  # When each listed object is up, to ten minutes over the next twelve hours:
  # `up` now, `sets_at` (nil: up the whole time), or `rises_at` if not yet.
  # The sky turns the same for every object, so sidereal time is worked out
  # once per step and shared.
  #
  # At night a window also ends at dawn (civil twilight, the Sun 6° down): a
  # star that "stays up until noon" is no use to anyone.
  defp windows(objects, now, site, horizon) do
    dark? = fn t -> Ephemeris.sun_alt(t, site) < -6.0 end
    night? = dark?.(now)

    steps =
      for m <- 0..720//10,
          t = DateTime.add(now, m * 60),
          do: {t, Astro.lst_deg(t, site.lon), not night? or dark?.(t)}

    Enum.map(objects, fn o ->
      up? = fn {_t, lst, dark} ->
        {alt, az} = Astro.alt_az(o.ra_deg, o.dec_deg, site.lat, lst)
        dark and alt > Settings.horizon_at(horizon, az)
      end

      [first | _] = steps

      if up?.(first) do
        sets = Enum.find(steps, &(not up?.(&1)))
        Map.merge(o, %{up: true, rises_at: nil, sets_at: sets && elem(sets, 0), dawn: match?({_, _, false}, sets)})
      else
        after_rise = Enum.drop_while(steps, &(not up?.(&1)))
        rises = List.first(after_rise)
        sets = rises && Enum.find(after_rise, &(not up?.(&1)))

        Map.merge(o, %{
          up: false,
          rises_at: rises && elem(rises, 0),
          sets_at: sets && elem(sets, 0),
          dawn: match?({_, _, false}, sets)
        })
      end
    end)
  end

  # A casual top five shouldn't be five bright stars: at most two stars up top,
  # the rest are the best deep-sky objects, then everything else in order.
  defp diversify(ranked) do
    {stars, dsos} = Enum.split_with(ranked, &(&1.kind == :star))
    top = Enum.take(stars, 2) ++ Enum.take(dsos, 3)
    top_ids = MapSet.new(top, & &1.id)
    Enum.sort_by(top, & &1.wow, :desc) ++ Enum.reject(ranked, &MapSet.member?(top_ids, &1.id))
  end

  defp messier_bonus(%{id: id}) when id in @showpieces, do: 3.5
  defp messier_bonus(%{proper: p}) when p in @showpiece_stars, do: 1.0
  defp messier_bonus(%{id: "m" <> rest}) when rest != "", do: 1.5
  defp messier_bonus(_), do: 0.0

  # Bright stars are nice but they're points; bias toward things with structure.
  defp kind_bonus(:star), do: -1.0

  defp kind_bonus(:moon), do: 6.0
  defp kind_bonus(:planet), do: 5.0
  defp kind_bonus(:planetary), do: 2.0
  defp kind_bonus(:galaxy), do: 1.5
  defp kind_bonus(:nebula), do: 1.5
  defp kind_bonus(:cluster), do: 1.0
  defp kind_bonus(_), do: 0.0

  # -- equipment & sky conditions (the parameters behind the casual list) --------------------------

  # Faintest star a scope shows under a suburban sky: 7.5 + 5·log10(D cm), minus ~1.5 for the
  # sky glow you get in a driveway. 0 mm means naked eye.
  def limiting_mag(aperture_mm) when aperture_mm <= 0, do: 4.5
  def limiting_mag(aperture_mm), do: 7.5 + 5 * :math.log10(aperture_mm / 10) - 1.5

  # Galaxies and nebulae are spread out: they need ~3 magnitudes of headroom.
  defp extended_margin(:galaxy), do: 3.5
  defp extended_margin(:nebula), do: 3.0
  defp extended_margin(:cluster), do: 1.5
  defp extended_margin(:planetary), do: 1.0
  defp extended_margin(_), do: 0.0

  defp showable?(%{kind: k, mag: m}, lim, _moon), do: m <= lim - extended_margin(k)

  defp moon_state(now, site, lst) do
    p = Ephemeris.position(:moon, now, site)
    {alt, _az} = Astro.alt_az(p.ra_deg, p.dec_deg, site.lat, lst)
    %{up: alt > 0, illumination: p.illumination}
  end

  # A bright Moon washes out the faint fuzzies, not the planets or clusters.
  defp moon_penalty(%{kind: k}, %{up: true, illumination: i}) when k in [:galaxy, :nebula],
    do: 3.0 * i

  defp moon_penalty(_, _), do: 0.0

  # Magnitude translated for this scope and this sky. Nobody remembers the scale.
  defp words(%{kind: :moon}, _lim, _moon), do: "Can't miss it"
  defp words(%{kind: :planet}, _lim, _moon), do: "Bright, easy"

  defp words(%{kind: k, mag: m}, lim, moon) do
    headroom = lim - extended_margin(k) - m

    base =
      cond do
        m <= 1.5 -> "Naked eye, obvious"
        m <= 4.0 and k == :star -> "Naked eye"
        m <= 4.5 and k != :star -> "Naked eye, faint smudge · great in the telescope"
        headroom >= 3 -> "Easy in the telescope"
        headroom >= 1 -> "In the telescope"
        headroom >= 0 -> "Faint, needs dark-adapted eyes"
        true -> "Too faint for this telescope"
      end

    if k in [:galaxy, :nebula] and moon.up and moon.illumination > 0.5,
      do: base <> " · washed out by the Moon",
      else: base
  end

  # -- render ------------------------------------------------------------------------------------------

  @doc """
  How far off the crosshair may be. The alignment's rms doubled (about 95% of
  pointings land inside it) with tracking's live error on top. Fewer than
  three alignment points can't be judged, and a mount with only home set is
  assumed polar-aligned: the page says so rather than draw a number it doesn't
  have.
  """
  def aim(nil, _tracker), do: :assumed
  def aim(%{solved?: false}, _tracker), do: :assumed
  def aim(%{n: n}, _tracker) when n < 3, do: {:unknown, n}

  def aim(%{n: n, rms_arcmin: rms}, tracker) do
    t = (tracker && tracker[:error_arcmin]) || 0.0
    {:margin, %{margin: :math.sqrt(4 * rms * rms + t * t), rms: rms, n: n, tracking: t}}
  end

  @doc "The margin on the map: a ring `r` degrees from (alt, az) on the sky, projected, so it is true to size at any altitude and zoom."
  def margin_ring(alt, az, r) do
    deg = :math.pi() / 180
    {a, z, d} = {alt * deg, az * deg, r * deg}

    Enum.map_join(0..348//12, " ", fn b ->
      b = b * deg
      a2 = :math.asin(:math.sin(a) * :math.cos(d) + :math.cos(a) * :math.sin(d) * :math.cos(b))

      z2 =
        z +
          :math.atan2(
            :math.sin(b) * :math.sin(d) * :math.cos(a),
            :math.cos(d) - :math.sin(a) * :math.sin(a2)
          )

      {x, y} = Astro.project(a2 / deg, z2 / deg)

      "#{:erlang.float_to_binary(x * 100, decimals: 3)},#{:erlang.float_to_binary(y * 100, decimals: 3)}"
    end)
  end

  def aim_words(:assumed), do: "Crosshair assumes a polar-aligned mount. Align to measure it"

  def aim_words({:unknown, n}),
    do: "Crosshair: margin unknown until a third alignment point (#{n} so far)"

  def aim_words({:margin, a}) do
    tracking = if a.tracking >= 0.1, do: " · tracking #{fmt1(a.tracking)}′", else: ""
    "Crosshair ±#{arc(a.margin)} · #{a.n} alignment points agree to #{fmt1(a.rms)}′" <> tracking
  end

  defp arc(arcmin) when arcmin >= 60, do: "#{fmt1(arcmin / 60)}°"
  defp arc(arcmin), do: "#{round(arcmin)}′"

  @impl true
  def render(assigns) do
    aim = aim(assigns.lineup, assigns.selected && Tracker.status(assigns.selected))

    # the telescope's crosshair and margin, only for the sky as it is now
    {scope, ring} =
      case assigns.shift_min == 0 && scope_radec(assigns.snap, assigns) do
        {ra, dec} ->
          xy = Scene.place(assigns.scene, ra, dec)
          ring = with {:margin, a} <- aim, do: Scene.ring(assigns.scene, ra, dec, a.margin / 60), else: (_ -> [])
          {xy && %{x: elem(xy, 0), y: elem(xy, 1)}, ring}

        _ ->
          {nil, []}
      end

    assigns = assign(assigns, scope: scope, ring: ring, aim: aim, views: Controller.Sky.Projection.views())

    ~H"""
    <%!-- one <main> per document: nested inside another page this is a plain block --%>
    <.dynamic_tag
      tag_name={if @nested, do: "div", else: "main"}
      class={["sky", @live_action == :tonight && "tonight", @night && "night", @nested && "nested"]}
      id="sky"
    >
      <%!-- nested inside another page, the header and STOP are that page's --%>
      <header :if={!@nested} class="page-header">
        <.back navigate={~p"/"} label="Home" section="Sky" />
        <.title>{if @live_action == :tonight, do: "Tonight", else: "Sky Map"}</.title>
        <%!-- when and where this sky is drawn: the Sky's status, the same on the Sky Map and Tonight --%>
        <.status label="When and where the sky is drawn">
          <SkyStatus.bar at={@at} shift_min={@shift_min} lst={@lst} utc_offset_min={@utc_offset_min} site={@site} trees={@trees} horizon={@horizon} sun={@sun} />
        </.status>
        <.actions>
          <.help href={~p"/docs/sky"} label="the sky" />
          <button class="ghost night-key" phx-click="night" aria-label="Night mode" aria-pressed={to_string(@night)}>◐</button>
          <.stop />
        </.actions>
      </header>
      <.skip_target :if={!@nested} />
      <%!-- the viewer's clock and time zone, for local time --%>
      <div id="sky-clock" phx-hook="Clock" hidden></div>

      <.link :if={Mount.simulated?(@selected)} navigate={~p"/devices"} class="hint sim-line">
        Simulator · no telescope on the cable · Devices ›
      </.link>
      <Controller.Components.Modes.modes :if={!@nested} modes={@modes} id={@selected} />

      <%!-- the sky takes the room, and stays up on a wide screen while the side shows a
            picked object or the horizon; on a phone the tabs switch between them --%>
      <%= if @live_action == :tonight do %>
        <%!-- Tonight: the list takes the room; beside it the plot for the five best, or the one picked --%>
        <.split class="sky-split">
          <:main>
            <section class="targets-wrap" aria-labelledby="targets-lede">
              <p class="horizon-hint" id="targets-lede">
                {if @trees, do: "Above your tree line", else: "Up"} now, best first.
              </p>
              <%!-- back to where it just was: the return-to-target test is one tap --%>
              <% recent = if @selected, do: Pointing.recent(@selected) |> Enum.filter(& &1["id"]), else: [] %>
              <nav :if={recent != []} class="recent" aria-label="Recent Go To targets">
                <span class="dim">Recent</span>
                <.link :for={r <- recent} navigate={~p"/object/#{r["id"]}?#{[mount: @selected, from: "tonight"]}"} class="btn">{r["name"]}</.link>
              </nav>
              <p :if={@locked == false} class="lock-line tone-caution" role="status">
                Not aligned yet, so Go To and tracking can't place anything. Open any bright star or planet, center it with the touchpad or the D-pad, and tap Centered. <.link href={~p"/docs/align"}>What's alignment?</.link>
              </p>
              <% {up, later} = Enum.split_with(@targets, & &1.up) %>
              <ol :if={up != []} class="targets" role="list">
                <%!-- a phone opens the object's page; a wide screen shows it beside the list --%>
                <li :for={{o, i} <- Enum.with_index(up, 1)}>
                  <.link
                    navigate={~p"/object/#{o.id}?#{[mount: @selected, from: "tonight"]}"}
                    class={["target", "pick-narrow", i <= 5 && "top"]}
                  >
                    <.target_body o={o} i={i} at={@at} utc_offset_min={@utc_offset_min} trees={@trees} horizon={@horizon} reach={@reach[o.id]} />
                  </.link>
                  <button
                    type="button"
                    class={["target", "pick-wide", i <= 5 && "top", @target && @target.id == o.id && "picked"]}
                    phx-click="pick"
                    phx-value-id={o.id}
                    aria-current={@target && @target.id == o.id && "true"}
                  >
                    <.target_body o={o} i={i} at={@at} utc_offset_min={@utc_offset_min} trees={@trees} horizon={@horizon} reach={@reach[o.id]} />
                    <span class="pick-arrow" aria-hidden="true">›</span>
                  </button>
                </li>
              </ol>
              <p :if={later != []} class="targets-head" id="targets-later">Rising later</p>
              <ol :if={later != []} class="targets later" role="list" aria-labelledby="targets-later">
                <li :for={o <- later}>
                  <.link navigate={~p"/object/#{o.id}?#{[mount: @selected, from: "tonight"]}"} class="target pick-narrow">
                    <.later_body o={o} at={@at} utc_offset_min={@utc_offset_min} />
                  </.link>
                  <button
                    type="button"
                    class={["target", "pick-wide", @target && @target.id == o.id && "picked"]}
                    phx-click="pick"
                    phx-value-id={o.id}
                    aria-current={@target && @target.id == o.id && "true"}
                  >
                    <.later_body o={o} at={@at} utc_offset_min={@utc_offset_min} />
                    <span class="pick-arrow" aria-hidden="true">›</span>
                  </button>
                </li>
              </ol>
              <p :if={@targets == []} class="horizon-hint">
                Nothing above the tree line. Lower it on <.link navigate={~p"/location"}>Location</.link> if that's wrong.
              </p>
            </section>
            <.sky_help />
          </:main>
          <:side>
            <%!-- when each of the five best is up, dusk to dawn, numbered as the list is;
                  beside the list on a wide screen, above it on a phone --%>
            <Controller.Components.Visibility.plot :if={is_nil(@target)} targets={Enum.take(Enum.filter(@targets, & &1.up), 5)} site={@site} at={@at} utc_offset_min={@utc_offset_min} horizon={if @trees, do: @horizon, else: nil} />
            <.pick_panel :if={@target} {pick_assigns(assigns)} />
          </:side>
        </.split>
      <% else %>
        <%!-- the Sky Map: the chart takes the whole width; a picked object's panel floats over its
              right side on a wide screen (under it on a phone), so picking never shrinks the sky --%>
        <div class="sky-stage">
          <%!-- the map is a picture to assistive tech: its objects are the Tonight list, which is the keyboard path (2.1.1) --%>
          <p id="skymap-note" class="sr-only">
            The map is a picture of the sky from {where(@site)}, with your tree line shaded. The Tonight page lists the same objects as links.
          </p>
          <div class="chart-wrap">
            <.chart
              id="skymap"
              scene={@scene}
              target={@target}
              scope={@scope}
              ring={@ring}
              path={@path}
              interactive
              label={"the sky from #{where(@site)}, #{view_name(@view)} chart#{if @target, do: ", #{@target.name} picked", else: ""}"}
              aria-describedby="skymap-note"
            />
            <%!-- the projection, over the chart's corner: the round dome, the flattened horizon, the mount's own axes --%>
            <.seg label="chart" class="sky-views">
              <:opt :for={{key, name, _} <- @views} on={key == @view} click="view" value={%{view: key}}>{name}</:opt>
            </.seg>
          </div>
          <.pick_panel :if={@target} {pick_assigns(assigns)} class={pick_side(@scene, @target)} />
        </div>
        <p class="fine sky-view-words">{view_words(@view)}</p>
        <p :if={!@target} class="hint sky-hint">
          Tap to pick, pinch to zoom<span :if={@snap && !@snap.homed && !@scope}>. Set home or align to see where the telescope points</span><span :if={!@snap}>. No mount</span>
        </p>
        <p :if={@scope && @shift_min == 0} class="hint sky-aim">{aim_words(@aim)}</p>
        <%!-- the telescope's reach: how faint it shows, and the Moon washing that out --%>
        <form phx-change="equipment" class="horizon sky-reach" aria-label="the telescope's reach">
          <label>
            Aperture mm<input name="aperture" type="text" inputmode="numeric" autocomplete="off" value={@aperture} />
          </label>
          <span class="hcell">Limit<span class="ro">mag {fmt1(@lim)}</span></span>
          <span class="hcell">Moon<span class="ro">{if @moon.up, do: "up · #{fmt0(@moon.illumination * 100)}%", else: "down"}</span></span>
          <span class="hcell"><span aria-hidden="true">&nbsp;</span><.help href={~p"/docs/magnitude"} label="magnitude and limit" /></span>
        </form>
        <.sky_help />
      <% end %>
      <.notice notice={@notice} />
    </.dynamic_tag>
    """
  end

  defp tree_at(true, horizon, az), do: Settings.horizon_at(horizon, az)
  defp tree_at(_, _, _), do: 0

  # One row of the Tonight list. Every row has the same columns, in this order, so each lines up
  # down the whole list (the row is a grid of fixed tracks, app.css): its number (or kind), the
  # name over its detail, how long it's up, and how high, drawn, last: at the row's far edge.
  # What Go To and the hold will do is words at the end of the detail line, never a column of its
  # own, so a row that has them is laid out exactly as one that hasn't.
  defp target_body(assigns) do
    ~H"""
    <span class="k" aria-hidden="true">{if @i <= 5, do: "#{@i}", else: glyph(@o.kind)}</span>
    <span class="t">
      <strong>{@o.name}</strong>
      <span class="d">
        <span>{fmt0(@o.alt)}° up · {compass(@o.az)} · {@o.words}<span :if={trees_class(@o.alt, tree_at(@trees, @horizon, @o.az)) == "near"}> · just over the trees</span></span>
        <span :if={r = @reach} class={["reach-short", "tone-#{r.tone}"]}><span aria-hidden="true">{r.mark} </span>{r.text}</span>
      </span>
    </span>
    <span class={["when", sets_soon?(@o, @at) && "soon"]}>{window_words(@o, @at, @utc_offset_min)}</span>
    <.height alt={@o.alt} tree={tree_at(@trees, @horizon, @o.az)} />
    """
  end

  # not up yet: the same columns, with nothing to draw in the last
  defp later_body(assigns) do
    ~H"""
    <span class="k" aria-hidden="true">{glyph(@o.kind)}</span>
    <span class="t">
      <strong>{@o.name}</strong>
      <span class="d"><span>{compass(@o.az)} · {@o.words}</span></span>
    </span>
    <span class="when">{window_words(@o, @at, @utc_offset_min)}</span>
    """
  end

  # what the picked object's panel needs from the page
  defp pick_assigns(assigns) do
    Map.take(assigns, [:target, :stars, :dsos, :lim, :moon, :scene, :live_action, :utc_offset_min, :site, :at, :trees, :horizon, :snap, :selected])
  end

  # the picked object: what it is, when it's up, and on Tonight its path across the sky
  # (the Sky Map's own chart draws that already)
  # the panel floats on the side of the chart away from the object, so it never covers it
  defp pick_side(scene, %{ra_deg: ra, dec_deg: dec}) do
    case Scene.place(scene, ra, dec) do
      {x, y} -> if elem(SkyChart.pct(scene.frame, x, y), 0) > 55, do: "pick-left"
      nil -> nil
    end
  end

  defp pick_panel(assigns) do
    assigns = assign_new(assigns, :class, fn -> nil end)

    ~H"""
    <section class={["pick-panel", @class]} aria-labelledby="pick-name">
      <div class="pick-head">
        <h2 id="pick-name">{@target.name}</h2>
        <button type="button" class="ghost pick-close" phx-click="clear" aria-label={"Close #{@target.name}"}>
          <Controller.Components.Icons.icon name="close" />
        </button>
      </div>
      <p class="dim" role="status">{describe(@target, @stars ++ @dsos, @lim, @moon, @scene)}</p>
      <Controller.Components.NightPath.figure :if={@live_action == :tonight} id="pick-path" scene={@scene} obj={@target} utc_offset_min={@utc_offset_min} />
      <Controller.Components.Visibility.plot targets={[@target]} site={@site} at={@at} utc_offset_min={@utc_offset_min} horizon={if @trees, do: @horizon, else: nil} />
      <div class="row">
        <button class="go" phx-click="goto" disabled={!@snap || !@snap.connected} aria-label={"Go To #{@target.name}"}>Go To</button>
        <.link navigate={~p"/object/#{@target.id}?#{[mount: @selected, from: if(@live_action == :tonight, do: "tonight", else: nil)]}"} class="btn" aria-label={"Details about #{@target.name}"}>Details ›</.link>
      </div>
    </section>
    """
  end

  defp sky_help(assigns) do
    ~H"""
    <p class="fine">
      <.link href={~p"/docs/sky"} class="help">How the sky page works</.link>
      · <.link href={~p"/docs/magnitude"} class="help">Magnitude in plain words</.link>
    </p>
    """
  end

  defp view_name(view), do: Enum.find_value(Controller.Sky.Projection.views(), "dome", fn {k, n, _} -> if k == view, do: String.downcase(n) end)
  defp view_words(view), do: Enum.find_value(Controller.Sky.Projection.views(), "", fn {k, _, w} -> if k == view, do: w end)



  defp describe(t, placed, lim, moon, scene) do
    case Enum.find(placed, &(&1.id == t.id)) || Scene.dir(scene, t.ra_deg, t.dec_deg) do
      %{alt: alt, az: az} = p when alt > 0 ->
        "alt #{fmt0(alt)}° · #{compass(az)} (#{fmt0(az)}°) · mag #{t.mag} · #{words(t, lim, moon)}" <>
          if(p[:hidden], do: " · below your tree line", else: "")

      _ ->
        "below the horizon · mag #{t.mag}"
    end
  end

  defp glyph(:moon), do: "☾"
  defp glyph(:planet), do: "Pl"
  defp glyph(:planetary), do: "Pn"
  defp glyph(:galaxy), do: "Gal"
  defp glyph(:nebula), do: "Neb"
  defp glyph(:cluster), do: "Cl"
  defp glyph(_), do: "★"

  # Until 23:40, Sets 20:10 (within the hour), All night, Rises 20:05: a time
  # in the viewer's zone rather than a sign to decode
  # How high it is, drawn: a quarter circle from the horizon to overhead, a line
  # at the object's height, and the tree line in that direction shaded in, so
  # "just over the trees" and "well clear" read at a glance.
  attr :alt, :any, required: true
  attr :tree, :any, default: 0

  defp height(assigns) do
    rad = fn deg -> max(min(deg, 90), 0) * :math.pi() / 180 end
    at = fn deg -> {4 + 32 * :math.cos(rad.(deg)), 36 - 32 * :math.sin(rad.(deg))} end
    {lx, ly} = at.(assigns.alt)
    {tx, ty} = at.(assigns.tree)
    # the number sits in whichever corner the line leaves empty
    {nx, ny, anchor} = if assigns.alt >= 45, do: {37, 33, "end"}, else: {6, 21, "start"}

    assigns =
      assign(assigns,
        lx: fmt1(lx),
        ly: fmt1(ly),
        tx: fmt1(tx),
        ty: fmt1(ty),
        nx: nx,
        ny: ny,
        anchor: anchor,
        deg: "#{round(max(assigns.alt, 0))}°"
      )

    ~H"""
    <svg class={["height", trees_class(@alt, @tree)]} viewBox="0 0 40 40" aria-hidden="true">
      <path :if={@tree > 0} d={"M4,36 L36,36 A32,32 0 0,0 #{@tx},#{@ty} Z"} class="height-trees" />
      <path d="M36,36 A32,32 0 0,0 4,4" class="height-arc" />
      <line x1="4" y1="36" x2="36" y2="36" class="height-arc" />
      <line x1="4" y1="36" x2={@lx} y2={@ly} class="height-line" />
      <text x={@nx} y={@ny} text-anchor={@anchor} class="height-deg">{@deg}</text>
    </svg>
    """
  end

  # The one look for "the trees may be in the way", everywhere a sky is drawn: just over the tree
  # line (it's an approximation, so a few degrees of doubt) is a lighter fade, behind it a deeper one.
  @near_trees 8

  defp trees_class(alt, tree) when tree > 0 and alt < tree, do: "behind"
  defp trees_class(alt, tree) when tree > 0 and alt - tree < @near_trees, do: "near"
  defp trees_class(_, _), do: nil

  defp window_words(%{up: true, sets_at: nil}, _now, _off), do: "All night"
  defp window_words(%{up: true, sets_at: t, dawn: true}, _now, off), do: "Until dawn, #{hm(t, off)}"

  defp window_words(%{up: true, sets_at: t} = o, now, off),
    do: "#{if sets_soon?(o, now), do: "Sets", else: "Until"} #{hm(t, off)}"

  defp window_words(%{up: false, rises_at: nil}, _now, _off), do: "Not tonight"
  defp window_words(%{up: false, rises_at: t}, _now, off), do: "Rises #{hm(t, off)}"

  defp sets_soon?(%{up: true, sets_at: %DateTime{} = t}, now), do: DateTime.diff(t, now) <= 3600
  defp sets_soon?(_, _), do: false

  defp hm(t, nil), do: Calendar.strftime(t, "%H:%M") <> " UTC"
  defp hm(t, off), do: Calendar.strftime(DateTime.add(t, off * 60, :second), "%H:%M")

  defp compass(az) do
    Enum.at(~w(N NE E SE S SW W NW), round(Astro.norm360(az) / 45) |> rem(8))
  end

  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)

  defp where(%{set: true} = site), do: latlon(site)
  defp where(_), do: "latitude 0, longitude 0 (no location set)"

  # 37.77° N 122.42° W: a kilometre, enough to tell the sky is yours
  defp latlon(%{lat: lat, lon: lon}),
    do:
      "#{:erlang.float_to_binary(abs(lat) * 1.0, decimals: 2)}° #{if lat >= 0, do: "N", else: "S"} #{:erlang.float_to_binary(abs(lon) * 1.0, decimals: 2)}° #{if lon >= 0, do: "E", else: "W"}"

  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)
end
