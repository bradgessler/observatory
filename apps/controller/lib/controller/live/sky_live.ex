defmodule Controller.SkyLive do
  @moduledoc """
  The sky from where you're standing, right now: stars to mag 5, Messier and
  named DSOs, constellation lines, and your local tree line shaded out. Tap
  anything and the selected mount slews to it. "Tonight" ranks what you can
  actually see over the next couple of hours from this spot.

  Pointing is a first-order model and says so in the UI: homed at the pole
  with the counterweight down, axis signs from `config :controller, :pointing`.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Controller.Sky.{Astro, Catalog, Ephemeris, HorizonScan, Solve, Pointing}

  @tick_ms 15_000
  @mag_limit 5.0
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

    # nested inside the bench, the mount id arrives in the session
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
       photo_cols: nil,
       photo_dims: nil,
       solving: false,
       solve_note: nil,
       now: DateTime.utc_now(),
       refs: %{},
       snap: nil,
       selected: params["id"],
       target: nil,
       notice: nil,
       page_title: "Sky",
       tab: "map"
     )
     # JPEG/PNG only: iOS converts HEIC to JPEG when HEIC isn't in the accept list,
     # and the solver can't read HEIC anyway.
     |> allow_upload(:photo, accept: ~w(.jpg .jpeg .png), max_entries: 1, max_file_size: 30_000_000, auto_upload: true)
     |> rescan()
     |> compute()}
  end

  # No handle_params: this view is also nested inside the bench (child views may
  # not define it). Mount and rescan pick the mount.

  # -- live updates ---------------------------------------------------------------------

  @impl true
  def handle_info(:tick, socket), do: {:noreply, socket |> assign(now: DateTime.utc_now()) |> compute()}

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
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:solved, {:ok, sol, profile}}, socket) do
    horizon = HorizonScan.merge(socket.assigns.horizon, profile)
    Settings.put("horizon", horizon)

    summary =
      profile |> Enum.sort_by(fn {s, _} -> Enum.find_index(Settings.sectors(), &(&1 == s)) end) |> Enum.map_join(", ", fn {s, a} -> "#{s} #{a}°" end)

    note =
      "solved: photo centered RA #{fmt1(sol.ra_deg / 15)}h Dec #{fmt1(sol.dec_deg)}°, #{fmt0(sol.radius_deg * 2)}° across" <>
        if(profile == %{}, do: "; no tree line found in frame", else: "; tree line → #{summary}")

    {:noreply, socket |> assign(horizon: horizon, solving: false, solve_note: note, photo_cols: nil) |> compute()}
  end

  def handle_info({:solved, {:error, reason}}, socket) do
    {:noreply, assign(socket, solving: false, solve_note: "solve failed: #{inspect(reason)}")}
  end

  def handle_info(:search_step, %{assigns: %{search: nil}} = socket), do: {:noreply, socket}

  def handle_info(:search_step, %{assigns: %{search: %{steps: steps, n: n} = search, snap: snap}} = socket) do
    stopped? = is_map(snap) and is_integer(snap[:estop_at]) and snap.estop_at > Map.get(search, :started, 0)

    case (if stopped?, do: :stopped, else: Enum.at(steps, n)) do
      :stopped ->
        {:noreply, assign(socket, search: nil, notice: "search stopped")}

      nil ->
        {:noreply, assign(socket, search: nil, notice: "search finished; nothing? try a wider eyepiece or re-check home")}

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
        d when d in ["forward", "reverse"] -> safe(fn -> Mount.configure(ref, tracking_direction: String.to_atom(d)) end)
        _ -> :ok
      end
    end
    socket = assign(socket, refs: refs)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: first_id(socket)
    snap = if ref = refs[selected], do: safe_snapshot(ref)
    assign(socket, selected: selected, snap: snap)
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Enum.sort() |> List.first()

  # Config gives the defaults; anything changed from the Horizon tab overrides them.
  defp site_setting do
    base = Application.get_env(:controller, :site, %{lat: 0.0, lon: 0.0, name: "nowhere"})

    case Settings.get("site") do
      %{"lat" => lat, "lon" => lon} when is_number(lat) and is_number(lon) -> %{base | lat: lat / 1, lon: lon / 1}
      _ -> base
    end
  end

  defp pointing_setting do
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    case Settings.get("pointing") do
      %{"ha_sign" => h, "dec_sign" => d} when h in [-1, 1] and d in [-1, 1] -> %{ha_sign: h, dec_sign: d}
      _ -> base
    end
  end

  defp flip_pointing(socket, key) do
    p = Map.update!(socket.assigns.pointing, key, &(-&1))
    Settings.put("pointing", %{"ha_sign" => p.ha_sign, "dec_sign" => p.dec_sign})
    # the sync offset was measured under the old signs; it's meaningless now
    Settings.put("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})
    assign(socket, pointing: p, offset: %{"ra" => 0.0, "dec" => 0.0}, notice: "#{key} flipped; sync offset cleared; re-Sync on a star")
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> :error
    end
  end

  defp coord(v, max) when is_number(v) and abs(v) <= max, do: {:ok, v / 1}

  defp coord(v, max) when is_binary(v) do
    case Float.parse(v) do
      {f, _} when abs(f) <= max -> {:ok, f}
      _ -> :error
    end
  end

  defp coord(_, _), do: :error

  defp upload_in_progress?(socket) do
    {_done, in_progress} = uploaded_entries(socket, :photo)
    in_progress != []
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
    target = Catalog.object(id) || Enum.find(Ephemeris.objects(socket.assigns.now), &(&1.id == id))
    {:noreply, assign(socket, target: target, notice: nil, tab: "map")}
  end

  def handle_event("clear", _, socket), do: {:noreply, assign(socket, target: nil, notice: nil)}

  def handle_event("night", _, socket) do
    night = !socket.assigns.night
    Settings.put("night", night)
    {:noreply, assign(socket, night: night)}
  end
  def handle_event("tab", %{"tab" => tab}, socket), do: {:noreply, assign(socket, tab: tab)}

  # -- photo → obstructions ------------------------------------------------------------------------

  def handle_event("validate", _params, socket), do: {:noreply, socket}

  def handle_event("photo_cols", %{"cols" => cols, "width" => w, "height" => h}, socket) do
    {:noreply, assign(socket, photo_cols: cols, photo_dims: {w, h}, solve_note: nil)}
  end

  def handle_event("solve", _params, %{assigns: %{photo_cols: cols}} = socket) when is_list(cols) do
    cond do
      not Solve.configured?() ->
        {:noreply, assign(socket, solve_note: "no NOVA_API_KEY set; can't solve")}

      socket.assigns.solving ->
        {:noreply, socket}

      upload_in_progress?(socket) ->
        {:noreply, assign(socket, solve_note: "still uploading the photo… try again in a moment")}

      true ->
        paths =
          consume_uploaded_entries(socket, :photo, fn %{path: path}, entry ->
            dest = Path.join(System.tmp_dir!(), "sky-#{System.unique_integer([:positive])}#{Path.extname(entry.client_name)}")
            File.cp!(path, dest)
            {:ok, dest}
          end)

        case paths do
          [path] ->
            site = socket.assigns.site
            dims = socket.assigns.photo_dims
            taken_at = DateTime.utc_now()
            boundary = for [x, y] <- cols, y < 1.0, do: {x, y}
            lv = self()

            Task.start(fn ->
              result =
                with {:ok, sol} <- Solve.solve(path) do
                  {:ok, sol, HorizonScan.profile(sol, boundary, site, taken_at, dims)}
                end

              File.rm(path)
              send(lv, {:solved, result})
            end)

            {:noreply, assign(socket, solving: true, solve_note: "uploaded; solving at nova.astrometry.net…")}

          _ ->
            {:noreply, assign(socket, solve_note: "pick a photo first")}
        end
    end
  end

  def handle_event("solve", _params, socket), do: {:noreply, assign(socket, solve_note: "pick a photo first")}

  # Field calibration without a rebuild: flip an axis sign if the map slews to the
  # mirror image; flip tracking if a star drifts out faster with tracking on.
  def handle_event("flip", %{"what" => "ra"}, socket), do: {:noreply, flip_pointing(socket, :ha_sign)}
  def handle_event("flip", %{"what" => "dec"}, socket), do: {:noreply, flip_pointing(socket, :dec_sign)}

  def handle_event("flip", %{"what" => "tracking"}, socket) do
    dir = if Settings.get("tracking_direction", "forward") == "forward", do: "reverse", else: "forward"
    Settings.put("tracking_direction", dir)
    for {_id, ref} <- socket.assigns.refs, do: safe(fn -> Mount.configure(ref, tracking_direction: String.to_atom(dir)) end)
    {:noreply, assign(socket, notice: "tracking direction now #{dir}")}
  end

  def handle_event("auto_track", _, socket) do
    v = !socket.assigns.auto_track
    Settings.put("auto_track", v)
    {:noreply, assign(socket, auto_track: v)}
  end

  # From the lat/lon inputs (strings) or the phone's geolocation (numbers).
  def handle_event("site", %{"lat" => lat, "lon" => lon} = params, socket) do
    with {:ok, la} <- coord(lat, 90), {:ok, lo} <- coord(lon, 180) do
      Settings.put("site", %{"lat" => la, "lon" => lo})
      from_phone? = is_number(lat)
      note = if from_phone?, do: "site set from your phone (±#{round(params["accuracy"] || 0)} m)", else: nil
      {:noreply, socket |> assign(site: %{socket.assigns.site | lat: la, lon: lo, name: if(from_phone?, do: "here", else: socket.assigns.site.name)}, notice: note) |> compute()}
    else
      # say what is wrong with what was typed (3.3.1); nothing is saved until it is right
      _ -> {:noreply, assign(socket, notice: "site not saved: latitude is −90 to 90, longitude −180 to 180")}
    end
  end

  def handle_event("site_error", %{"reason" => r}, socket), do: {:noreply, assign(socket, notice: "location: #{r}")}

  def handle_event("equipment", %{"aperture" => a}, socket) do
    aperture =
      case Integer.parse(a) do
        {n, _} -> n |> max(0) |> min(1_000)
        :error -> socket.assigns.aperture
      end

    Settings.put("aperture_mm", aperture)
    {:noreply, socket |> assign(aperture: aperture) |> compute()}
  end

  def handle_event("horizon", params, socket) do
    horizon =
      for s <- Settings.sectors(), into: %{} do
        v =
          case Integer.parse(params[s] || "") do
            {n, _} -> n |> max(0) |> min(89)
            :error -> socket.assigns.horizon[s] || 20
          end

        {s, v}
      end

    Settings.put("horizon", horizon)
    {:noreply, socket |> assign(horizon: horizon) |> compute()}
  end

  def handle_event("goto", _, %{assigns: %{target: t, snap: snap}} = socket) when not is_nil(t) do
    ref = socket.assigns.refs[socket.assigns.selected]

    notice =
      case Pointing.slew(ref, snap, t, ctx(socket.assigns), track: socket.assigns.auto_track) do
        {:ok, d_ra, d_dec} -> "slewing to #{t.name} (ΔRA #{fmt1(d_ra)}°, ΔDec #{fmt1(d_dec)}°)"
        {:error, :not_connected} -> "no mount connected"
        {:error, :not_homed} -> "zero the axes first (Setup, mount upright); it arms the cable-safety limits"
        {:error, :limit} -> "#{t.name} is outside the soft limits"
        {:error, e} -> inspect(e)
      end

    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("goto", _, socket), do: {:noreply, socket}

  def handle_event("stop", _, socket) do
    Controller.Sky.Tracker.stop(socket.assigns.selected)
    if ref = socket.assigns.refs[socket.assigns.selected], do: Mount.stop(ref)
    {:noreply, assign(socket, notice: "stopped", search: nil)}
  end

  # "The scope is centred on the target right now." One tap is a one-star sync;
  # each further star tightens the alignment (Controller.Sky.Lineup).
  def handle_event("sync", _, %{assigns: %{target: t, snap: snap}} = socket) when not is_nil(t) do
    if snap && snap.homed do
      st = Pointing.sync(snap, t, ctx(socket.assigns))
      {:noreply, assign(socket, notice: "aligned on #{t.name} · #{st.n} star#{if st.n == 1, do: "", else: "s"} · agree to #{fmt1(st.rms_arcmin || 0.0)}′")}
    else
      {:noreply, assign(socket, notice: "zero the axes first (Setup)")}
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
      {:noreply, assign(socket, search: %{steps: spiral(), n: 0, started: System.monotonic_time(:millisecond)}, notice: "searching around #{t.name}… Stop when you see it")}
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

  # -- sky computation (once per tick, not per render) ----------------------------------------------

  defp compute(socket) do
    %{now: now, site: site, horizon: horizon} = socket.assigns
    lst = Astro.lst_deg(now, site.lon)

    place = fn o ->
      {alt, az} = Astro.alt_az(o.ra_deg, o.dec_deg, site.lat, lst)
      {x, y} = Astro.project(alt, az)
      Map.merge(o, %{alt: alt, az: az, x: x * 100, y: y * 100, hidden: alt < Settings.horizon_at(horizon, az)})
    end

    aperture = socket.assigns.aperture
    stars = for o <- Catalog.stars(@mag_limit), o = place.(o), o.alt > -1, do: o
    sol = for o <- Ephemeris.objects(now), o = place.(o), o.alt > -1, do: o
    dsos = sol ++ for(o <- Catalog.dsos(), o.mag < 10, o = place.(o), o.alt > -1, do: o)

    lines =
      for line <- Catalog.lines(),
          pts = Enum.map(line, fn {ra, dec} -> Astro.alt_az(ra, dec, site.lat, lst) end),
          Enum.all?(pts, fn {alt, _} -> alt > -3 end) do
        Enum.map_join(pts, " ", fn {alt, az} ->
          {x, y} = Astro.project(alt, az)
          "#{fmt1(x * 100)},#{fmt1(y * 100)}"
        end)
      end

    treeline =
      Enum.map_join(0..360//5, " ", fn az ->
        {x, y} = Astro.project(Settings.horizon_at(horizon, az), az)
        "#{fmt1(x * 100)},#{fmt1(y * 100)}"
      end)

    assign(socket,
      lst: lst,
      stars: stars,
      dsos: dsos,
      lines: lines,
      treeline: treeline,
      modes: Controller.Modes.active(),
      lim: limiting_mag(aperture),
      moon: moon_state(now, site, lst),
      targets: targets(now, site, horizon, aperture)
    )
  end

  # What's worth looking at from this spot, with this scope, over the next two hours.
  # Public: the agent/sky-tour layer (#8, #40) calls this same function.
  def targets(now, site, horizon, aperture_mm) do
    lsts = for h <- [0, 1, 2], do: Astro.lst_deg(DateTime.add(now, h * 3600), site.lon)
    lim = limiting_mag(aperture_mm)
    moon = moon_state(now, site, hd(lsts))

    candidates =
      Ephemeris.objects(now) ++
        Catalog.dsos() ++
        Enum.filter(Catalog.stars(4.0), &(&1.proper != nil and (&1.mag <= 2.6 or &1.proper in @showpiece_stars)))

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
    p = Ephemeris.position(:moon, now)
    {alt, _az} = Astro.alt_az(p.ra_deg, p.dec_deg, site.lat, lst)
    %{up: alt > 0, illumination: p.illumination}
  end

  # A bright Moon washes out the faint fuzzies, not the planets or clusters.
  defp moon_penalty(%{kind: k}, %{up: true, illumination: i}) when k in [:galaxy, :nebula], do: 3.0 * i
  defp moon_penalty(_, _), do: 0.0

  # Magnitude translated for this scope and this sky. Nobody remembers the scale.
  defp words(%{kind: :moon}, _lim, _moon), do: "can't miss it"
  defp words(%{kind: :planet}, _lim, _moon), do: "bright, easy"

  defp words(%{kind: k, mag: m}, lim, moon) do
    headroom = lim - extended_margin(k) - m

    base =
      cond do
        m <= 1.5 -> "naked eye, obvious"
        m <= 4.0 and k == :star -> "naked eye"
        m <= 4.5 and k != :star -> "naked eye, faint smudge · great in the scope"
        headroom >= 3 -> "easy in the scope"
        headroom >= 1 -> "in the scope"
        headroom >= 0 -> "faint, needs dark-adapted eyes"
        true -> "too faint for this scope"
      end

    if k in [:galaxy, :nebula] and moon.up and moon.illumination > 0.5,
      do: base <> " · washed out by the Moon",
      else: base
  end

  # -- render ------------------------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    scope =
      case scope_radec(assigns.snap, assigns) do
        {ra, dec} ->
          {alt, az} = Astro.alt_az(ra, dec, assigns.site.lat, assigns.lst)
          {x, y} = Astro.project(max(alt, -5.0), az)
          %{x: x * 100, y: y * 100}

        nil ->
          nil
      end

    assigns = assign(assigns, scope: scope)

    ~H"""
    <%!-- one <main> per document: inside the bench this is a plain block --%>
    <.dynamic_tag tag_name={if @nested, do: "div", else: "main"} class={["sky", @night && "night", @nested && "nested"]} id="sky">
      <%!-- inside the bench the header, STOP and the modes chip are the bench's --%>
      <header :if={!@nested}>
        <.link navigate={~p"/"} class="ghost">‹ Start</.link>
        <h1>{@site[:name]} · {Calendar.strftime(@now, "%H:%M")} UTC · LST {fmt_h(@lst)}</h1>
        <span class="hdr-actions">
          <.stop />
          <button class="ghost" phx-click="night" aria-label="night mode" aria-pressed={to_string(@night)}>◐</button>
        </span>
      </header>
      <.skip_target :if={!@nested} />

      <.link :if={@selected == "sim"} navigate={~p"/devices"} class="hint sim-line">simulator · no telescope on the cable · Devices ›</.link>
      <Controller.Components.Modes.modes :if={!@nested} modes={@modes} id={@selected} />

      <.seg label="sky page" class="tabs">
        <:opt :for={{t, label} <- [{"map", "Map"}, {"targets", "Tonight"}, {"horizon", "Horizon"}]} on={t == @tab} click="tab" value={%{tab: t}}>{label}</:opt>
      </.seg>

      <%!-- the map is a picture to assistive tech: its objects are the Tonight list, which is the keyboard path (2.1.1) --%>
      <p :if={@tab == "map"} id="skymap-note" class="sr-only">The map is a picture of the sky from {@site[:name]} right now, north up, east left, with your tree line shaded. The Tonight tab lists the same objects as links.</p>
      <svg :if={@tab == "map"} id="skymap" phx-hook="SkyZoom" viewBox="-104 -104 208 208" class="map" phx-click="clear" role="img" aria-label={"the sky from #{@site[:name]}#{if @target, do: ", #{@target.name} picked", else: ""}"} aria-describedby="skymap-note">
        <defs>
          <radialGradient id="dome" cx="50%" cy="50%" r="50%">
            <stop offset="70%" stop-color="var(--sky1)" /><stop offset="100%" stop-color="var(--sky2)" />
          </radialGradient>
          <clipPath id="disc"><circle r="100" /></clipPath>
        </defs>
        <circle r="100" fill="url(#dome)" stroke="var(--edge)" stroke-width=".6" />
        <g clip-path="url(#disc)">
          <circle :for={alt <- [30, 60]} r={100 * :math.tan((90 - alt) / 2 * :math.pi() / 180) / :math.tan(:math.pi() / 4)} fill="none" stroke="var(--edge)" stroke-width=".3" stroke-dasharray="1 2" />
          <line x1="-100" y1="0" x2="100" y2="0" stroke="var(--edge)" stroke-width=".3" />
          <line x1="0" y1="-100" x2="0" y2="100" stroke="var(--edge)" stroke-width=".3" />

          <polyline :for={l <- @lines} points={l} class="lines" />

          <g :for={o <- @stars} phx-click="pick" phx-value-id={o.id} class={["obj", "star", o.mag > 3.5 && "faint", o.hidden && "hidden", @target && @target.id == o.id && "picked"]}>
            <circle class="hit" cx={o.x} cy={o.y} r={radius(o) + 3.5} />
            <circle cx={o.x} cy={o.y} r={radius(o)} />
            <text :if={o.proper && o.mag < 1.9} x={o.x + 2.2} y={o.y + 1}>{o.proper}</text>
          </g>

          <g :for={o <- @dsos} phx-click="pick" phx-value-id={o.id} class={["obj", o.kind, o.hidden && "hidden", @target && @target.id == o.id && "picked"]}>
            <circle class="hit" cx={o.x} cy={o.y} r="4.5" />
            <rect x={o.x - 1.5} y={o.y - 1.5} width="3" height="3" transform={"rotate(45 #{o.x} #{o.y})"} />
            <text :if={String.starts_with?(o.id, "sol-") or (o.mag < 6.5 and String.starts_with?(o.id, "m"))} x={o.x + 2.6} y={o.y + 1}>{short(o.name)}</text>
          </g>

          <path d={"M100,0 A100,100 0 1,1 -100,0 A100,100 0 1,1 100,0 Z M#{@treeline} Z"} fill-rule="evenodd" class="treeline" pointer-events="none" />
          <polygon points={@treeline} class="treeline-edge" pointer-events="none" />

          <g :if={@scope} class="scope" transform={"translate(#{fmt1(@scope.x)} #{fmt1(@scope.y)})"} pointer-events="none">
            <circle r="5" fill="none" />
            <line x1="-8" y1="0" x2="-3" y2="0" /><line x1="3" y1="0" x2="8" y2="0" />
            <line x1="0" y1="-8" x2="0" y2="-3" /><line x1="0" y1="3" x2="0" y2="8" />
          </g>
        </g>
        <text x="0" y="-101.5" class="card">N</text>
        <text x="0" y="103.5" class="card">S</text>
        <text x="-102" y="1" class="card" text-anchor="end">E</text>
        <text x="102" y="1" class="card" text-anchor="start">W</text>
      </svg>

      <section :if={@tab == "targets"} class="targets-wrap" aria-labelledby="targets-lede">
        <p class="horizon-hint" id="targets-lede">Above your tree line now, ranked by how good they look and how long they stay up.</p>
        <ol :if={@targets != []} class="targets" role="list">
          <li :for={{o, i} <- Enum.with_index(@targets, 1)}>
            <.link navigate={~p"/object/#{o.id}?#{[mount: @selected]}"} class={["target", i <= 5 && "top"]}>
              <span class="k" aria-hidden="true">{if i <= 5, do: "#{i}", else: glyph(o.kind)}</span>
              <span class="t"><strong>{o.name}</strong><span>{fmt0(o.alt)}° up · {compass(o.az)} · {o.words}</span></span>
              <span class={["when", when_class(o.status)]}>{when_text(o.status)}</span>
            </.link>
          </li>
        </ol>
        <p :if={@targets == []} class="horizon-hint">Nothing above the tree line. Lower it on the Horizon tab if that's wrong.</p>
      </section>

      <section :if={@tab == "horizon"} aria-label="horizon, equipment and site">
        <p class="horizon-hint">Tree line, degrees above level, each direction. <.help href={~p"/docs/horizon"} label="tree line" /></p>
        <form phx-change="horizon" class="horizon" aria-label="tree line by direction, degrees">
          <label :for={s <- Settings.sectors()}>{s}<input name={s} type="text" inputmode="numeric" autocomplete="off" value={@horizon[s]} /></label>
        </form>
        <form phx-change="equipment" class="horizon" aria-label="equipment">
          <label>aperture mm<input name="aperture" type="text" inputmode="numeric" autocomplete="off" value={@aperture} /></label>
          <span class="hcell">limit<span class="ro">mag {fmt1(@lim)}</span></span>
          <span class="hcell">Moon<span class="ro">{if @moon.up, do: "up · #{fmt0(@moon.illumination * 100)}%", else: "down"}</span></span>
          <span class="hcell"><span aria-hidden="true">&nbsp;</span><.help href={~p"/docs/magnitude"} label="magnitude and limit" /></span>
        </form>

        <div class="photo">
          <p class="horizon-hint">Site <.help href={~p"/docs/horizon"} label="site" /></p>
          <form phx-change="site" class="horizon" aria-label="site">
            <label>lat<input name="lat" type="text" inputmode="decimal" autocomplete="off" value={@site.lat} /></label>
            <label>lon<input name="lon" type="text" inputmode="decimal" autocomplete="off" value={@site.lon} /></label>
            <span class="hcell"><span aria-hidden="true">&nbsp;</span><button type="button" id="use-location" phx-hook="Geo" class="ro">Use my location</button></span>
            <span class="hcell"><span aria-hidden="true">&nbsp;</span><.link navigate={~p"/setup/#{@selected}"} class="ro">Setup ›</.link></span>
          </form>
        </div>

        <div class="photo" id="sky-photo" phx-hook="SkyPhoto">
          <p class="horizon-hint" id="photo-lede">Tree line from a Night-mode photo <.help href={~p"/docs/horizon"} label="tree line from a photo" /></p>
          <form phx-change="validate" phx-submit="solve" aria-labelledby="photo-lede">
            <.live_file_input upload={@uploads.photo} aria-label="a photo of the sky and tree line" />
            <button :if={@photo_cols && !@solving} class="go">Solve &amp; apply</button>
            <span :if={@solving} class="dim">solving… (30–90 s)</span>
          </form>
          <p :if={@photo_cols} class="horizon-hint">Traced {length(@photo_cols)} columns; sky/tree boundary found in {Enum.count(@photo_cols, fn [_, y] -> y < 1.0 end)} of them.</p>
          <p :if={@solve_note} class="horizon-hint">{@solve_note}</p>
          <p :if={!Solve.configured?()} class="horizon-hint">Solving needs <code>NOVA_API_KEY</code> (free at nova.astrometry.net).</p>
        </div>
      </section>

      <section class="pick" :if={@target} aria-label="picked object" aria-live="polite">
        <div>
          <strong>{@target.name}</strong>
          <span class="dim">{describe(@target, @stars ++ @dsos, @lim, @moon)}</span>
        </div>
        <button class="go" phx-click="goto" aria-label={"Slew to #{@target.name}"}>Slew</button>
        <.link navigate={~p"/object/#{@target.id}?#{[mount: @selected]}"} class="btn-link" aria-label={"Info about #{@target.name}"}>Info ›</.link>
      </section>
      <section class="pick hint" :if={!@target and @tab == "map"}>
        <span class="dim">
          Tap to pick · pinch to zoom
          <span :if={@snap && !@snap.homed}> · zero the axes to see the scope</span>
          <span :if={!@snap}> · no mount</span>
        </span>
      </section>

      <p class="fine"><.link href={~p"/docs/sky"} class="help">how the sky page works</.link> · <.link href={~p"/docs/magnitude"} class="help">magnitude in plain words</.link></p>
      <.notice notice={@notice} />
    </.dynamic_tag>
    """
  end

  defp radius(%{mag: m}), do: max(0.45, 2.4 - m * 0.45)

  defp short(name), do: name |> String.split(" ") |> List.first()

  defp describe(t, placed, lim, moon) do
    case Enum.find(placed, &(&1.id == t.id)) do
      %{alt: alt, az: az, hidden: hidden} ->
        "alt #{fmt0(alt)}° · #{compass(az)} (#{fmt0(az)}°) · mag #{t.mag} · #{words(t, lim, moon)}" <>
          if(hidden, do: " · below your tree line", else: "")

      _ ->
        "below the horizon · mag #{t.mag}"
    end
  end

  defp glyph(:moon), do: "☾"
  defp glyph(:planet), do: "pl"
  defp glyph(:planetary), do: "pn"
  defp glyph(:galaxy), do: "gal"
  defp glyph(:nebula), do: "neb"
  defp glyph(:cluster), do: "cl"
  defp glyph(_), do: "★"

  defp when_text(:good), do: "up 2h+"
  defp when_text(:sets_later), do: "sets <2h"
  defp when_text(:sets_soon), do: "sets <1h"
  defp when_text(:rising), do: "rises <2h"

  defp when_class(:sets_soon), do: "soon"
  defp when_class(:rising), do: "rising"
  defp when_class(_), do: nil

  defp compass(az) do
    Enum.at(~w(N NE E SE S SW W NW), round(Astro.norm360(az) / 45) |> rem(8))
  end

  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)

  defp fmt_h(deg) do
    h = deg / 15
    "#{trunc(h)}h#{:erlang.float_to_binary((h - trunc(h)) * 60, decimals: 0) |> String.pad_leading(2, "0")}m"
  end
end
