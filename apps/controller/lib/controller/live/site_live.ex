defmodule Controller.SiteLive do
  @moduledoc """
  Where the scope stands and what time it is, from the phone in your hand.

  A phone knows three things the box does not: where it is (its location,
  asked for from a tap), its time zone and whether daylight saving is on
  (always right on a phone), and a clock set by the carrier or the internet.
  So this page takes them from the phone and turns them into what a night
  of setup needs:

    * the polar axis altitude to set on an equatorial mount's latitude scale,
      and which pole to aim it at;
    * what a NexStar-style hand controller asks for, in its own terms: the
      time, Standard or Daylight Saving, the time zone as hours from UTC, the
      date, and latitude and longitude in degrees and minutes;
    * this machine's clock: set by the network, or (a box in a field, with no
      internet time) set from the phone.

  Location is saved as the site (`Controller.Settings` "site", what the sky
  and pointing already use), with its accuracy and where it came from.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Clock, Settings}
  alias Controller.Components.SkyChart
  alias Controller.Sky.{Astro, HorizonScan, Pointing, Scene, Solve}

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      :timer.send_interval(1_000, :tick)
    end

    {:ok,
     socket
     |> assign(page_title: "Location", night: Settings.get("night", false), notice: nil, phone: nil)
     |> assign(now: DateTime.utc_now(), site: site())
     |> assign(photo_cols: nil, photo_dims: nil, solving: false, solve_note: nil)
     |> trees()
     # JPEG/PNG only: iOS converts HEIC to JPEG when HEIC isn't in the accept list,
     # and the solver can't read HEIC anyway.
     |> allow_upload(:photo, accept: ~w(.jpg .jpeg .png), max_entries: 1, max_file_size: 30_000_000, auto_upload: true)}
  end

  # the tree line, and a dome with it drawn (the Sky Map's own layers, no stars), redrawn as it changes
  defp trees(socket) do
    # none set yet is a clear horizon here, as the toolbar says, not the stand-in the sky ranks against
    set? = Settings.get("horizon") != nil
    horizon = if set?, do: Settings.horizon(), else: Map.new(Settings.sectors(), &{&1, 0})
    site = Pointing.site()
    assign(socket, horizon: horizon, dome: Scene.build(DateTime.utc_now(), site, horizon, view: :dome, trees: set?, sky: false))
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}
  def handle_info({:settings, "site", _}, socket), do: {:noreply, socket |> assign(site: site()) |> trees()}
  def handle_info({:settings, "horizon", _}, socket), do: {:noreply, trees(socket)}

  def handle_info({:solved, {:ok, sol, profile}}, socket) do
    horizon = HorizonScan.merge(socket.assigns.horizon, profile)
    Settings.put("horizon", horizon)

    summary =
      profile
      |> Enum.sort_by(fn {s, _} -> Enum.find_index(Settings.sectors(), &(&1 == s)) end)
      |> Enum.map_join(", ", fn {s, a} -> "#{s} #{a}°" end)

    note =
      "Solved: the photo is centred at RA #{fmt(sol.ra_deg / 15, 1)}h Dec #{fmt(sol.dec_deg, 1)}°, #{round(sol.radius_deg * 2)}° across" <>
        if(profile == %{}, do: "; no tree line found in it", else: "; tree line: #{summary}")

    {:noreply, socket |> assign(solving: false, solve_note: note, photo_cols: nil) |> trees()}
  end

  def handle_info({:solved, {:error, reason}}, socket),
    do: {:noreply, assign(socket, solving: false, solve_note: "Plate solve failed: #{Controller.Words.error(reason)}")}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  # From the phone's location (numbers, with accuracy) or the typed fields (strings).
  @impl true
  # STOP is on every page: every mount this machine can reach
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("site", %{"lat" => lat, "lon" => lon} = params, socket) do
    with {:ok, la} <- coord(lat, 90), {:ok, lo} <- coord(lon, 180) do
      from_phone? = is_number(lat)

      Settings.put("site", %{
        "lat" => la,
        "lon" => lo,
        "accuracy_m" => if(from_phone?, do: params["accuracy"]),
        "source" => if(from_phone?, do: "phone", else: "typed"),
        "at" => DateTime.utc_now() |> DateTime.to_iso8601()
      })

      {:noreply, assign(socket, site: site(), notice: if(from_phone?, do: "Location set from this phone", else: "Location saved"))}
    else
      _ -> {:noreply, assign(socket, notice: "Not saved: latitude is -90 to 90, longitude -180 to 180")}
    end
  end

  def handle_event("site_error", %{"reason" => r}, socket), do: {:noreply, assign(socket, notice: Controller.Site.location_error(r))}

  # -- the tree line ----------------------------------------------------------------------

  # a slider moved: that direction's height, saved as it goes, so every sky redraws with it
  def handle_event("horizon", params, socket) do
    horizon =
      for s <- Settings.sectors(), into: %{} do
        v =
          case Integer.parse(to_string(params[s] || "")) do
            {n, _} -> n |> max(0) |> min(89)
            :error -> socket.assigns.horizon[s] || 0
          end

        {s, v}
      end

    Settings.put("horizon", horizon)
    {:noreply, trees(socket)}
  end

  def handle_event("horizon_clear", _, socket) do
    Settings.put("horizon", Map.new(Settings.sectors(), &{&1, 0}))
    {:noreply, trees(socket)}
  end

  # -- the tree line from a photo: traced in the browser (SkyPhoto), placed by a plate solve --

  def handle_event("validate", _params, socket), do: {:noreply, socket}

  def handle_event("photo_cols", %{"cols" => cols, "width" => w, "height" => h}, socket),
    do: {:noreply, assign(socket, photo_cols: cols, photo_dims: {w, h}, solve_note: nil)}

  def handle_event("solve", _params, %{assigns: %{photo_cols: cols}} = socket) when is_list(cols) do
    {_done, uploading} = uploaded_entries(socket, :photo)

    cond do
      not Solve.configured?() ->
        {:noreply, assign(socket, solve_note: "Plate solving online needs an astrometry.net API key; set NOVA_API_KEY on the machine running the server.")}

      socket.assigns.solving ->
        {:noreply, socket}

      uploading != [] ->
        {:noreply, assign(socket, solve_note: "Still uploading the photo… try again in a moment")}

      true ->
        paths =
          consume_uploaded_entries(socket, :photo, fn %{path: path}, entry ->
            dest = Path.join(System.tmp_dir!(), "sky-#{System.unique_integer([:positive])}#{Path.extname(entry.client_name)}")
            File.cp!(path, dest)
            {:ok, dest}
          end)

        case paths do
          [path] ->
            site = Pointing.site()
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

            {:noreply, assign(socket, solving: true, solve_note: "Uploaded; solving at nova.astrometry.net…")}

          _ ->
            {:noreply, assign(socket, solve_note: "Pick a photo first")}
        end
    end
  end

  def handle_event("solve", _params, socket), do: {:noreply, assign(socket, solve_note: "Pick a photo first")}

  # The phone's clock and time zone, sent once when the page connects.
  def handle_event("clock", %{"now_ms" => ms, "tz" => tz, "offset_min" => off, "std_offset_min" => std}, socket) do
    ours = System.os_time(:millisecond)
    phone = %{tz: tz, offset_min: off, std_offset_min: std, dst: off != std, skew_ms: ms - ours}

    notice =
      if Clock.settable?() and not Clock.synced?() and abs(phone.skew_ms) > 2_000 do
        case Clock.set(DateTime.from_unix!(ms, :millisecond)) do
          :ok -> "This box's clock was #{skew_words(phone.skew_ms)}; set from this phone"
          _ -> nil
        end
      end

    {:noreply, assign(socket, phone: phone, notice: notice || socket.assigns.notice, now: DateTime.utc_now())}
  end

  defp site do
    base = Pointing.site()
    saved = Settings.get("site")
    saved = if is_map(saved), do: saved, else: %{}

    %{
      lat: base.lat,
      lon: base.lon,
      # typed, from a phone, or the one in the config file: any of them is a location
      set: Pointing.site_set?(),
      accuracy_m: saved["accuracy_m"],
      source: saved["source"] || if(saved == %{}, do: "config"),
      at: parse_at(saved["at"])
    }
  end

  defp parse_at(nil), do: nil

  defp parse_at(iso) do
    case DateTime.from_iso8601(iso) do
      {:ok, dt, _} -> dt
      _ -> nil
    end
  end

  defp coord(v, max) when is_number(v) and abs(v) <= max, do: {:ok, v / 1}

  defp coord(v, max) when is_binary(v) do
    case Float.parse(String.trim(v)) do
      {f, ""} when abs(f) <= max -> {:ok, f}
      _ -> :error
    end
  end

  defp coord(_, _), do: :error

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="site" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="Alignment" />
        <.title>Location</.title>
        <%!-- the Alignment section's status: how well this telescope is aligned, the same as the sidebar's --%>
        <.status label="Alignment"><Controller.Components.AlignmentStatus.bar summary={(assigns[:alignments] || %{})[@telescope && @telescope.id]} /></.status>
        <.actions><.help href={~p"/docs/location"} label="location" /><.stop /></.actions>
      </:header>

      <div id="phone-clock" phx-hook="Clock" hidden></div>

      <.card title="Latitude and Longitude">
        <div :if={@site.set} class="site-coords" role="status">
          <p class="site-big">{dms(@site.lat, "N", "S")}<br />{dms(@site.lon, "E", "W")}</p>
          <.kv label="Decimal" value={"#{fmt(@site.lat, 5)}, #{fmt(@site.lon, 5)}"} />
          <.kv label="From" value={source_words(@site, @now)} />
        </div>
        <.hint :if={!@site.set}>Not set. Pointing assumes latitude 0 until it is.</.hint>
        <.phone_location id="use-phone-location" secure={@secure} />
        <form phx-submit="site" class="site-typed" aria-label="type the location">
          <label>Latitude <input name="lat" type="text" inputmode="decimal" class="field" value={if @site.set, do: fmt(@site.lat, 5)} /></label>
          <label>Longitude <input name="lon" type="text" inputmode="decimal" class="field" value={if @site.set, do: fmt(@site.lon, 5)} /></label>
          <.btn type="submit">Save</.btn>
        </form>
      </.card>

      <%!-- the horizon this location really has: how high the trees reach, by direction --%>
      <.card title="Tree Line" id="tree-line">
        <.hint>How high the trees, roofs or hills reach in each direction, in degrees above level. Anything lower is drawn faded on every sky chart and left off Tonight. <.link href={~p"/docs/horizon"}>About the tree line</.link></.hint>
        <div class="tree-edit">
          <SkyChart.frame id="tree-dome" scene={@dome} label="the tree line around the sky, from overhead" class="tree-dome">
            <SkyChart.grid scene={@dome} except={["equator", "ecliptic"]} />
            <SkyChart.trees scene={@dome} />
            <:over><SkyChart.grid_labels scene={@dome} /></:over>
          </SkyChart.frame>
          <form phx-change="horizon" class="tree-sliders" aria-label="tree line by direction">
            <label :for={s <- Settings.sectors()}>
              <span class="tree-dir">{s}</span>
              <input type="range" name={s} min="0" max="60" step="1" value={@horizon[s]} phx-throttle="120" aria-label={"#{s}, degrees above level"} />
              <output>{@horizon[s]}°</output>
            </label>
          </form>
        </div>
        <.row><.btn variant="ghost" phx-click="horizon_clear">Clear to the Horizon</.btn></.row>
      </.card>

      <.card title="Tree Line from a Photo">
        <div class="photo" id="sky-photo" phx-hook="SkyPhoto">
          <.hint>A night-mode photo of the sky over the trees, plate solved, sets the directions it covers. <.link href={~p"/docs/horizon"}>How</.link></.hint>
          <form phx-change="validate" phx-submit="solve" aria-label="a photo of the sky over the tree line">
            <.live_file_input upload={@uploads.photo} aria-label="a photo of the sky and tree line" />
            <button :if={@photo_cols && !@solving} class="go">Plate Solve &amp; Apply</button>
            <span :if={@solving} class="dim">Plate solving… (30–90 s)</span>
          </form>
          <.hint :if={@photo_cols}>Traced {length(@photo_cols)} columns; the sky and tree boundary found in {Enum.count(@photo_cols, fn [_, y] -> y < 1.0 end)} of them.</.hint>
          <.hint :if={@solve_note} role="status">{@solve_note}</.hint>
          <.hint :if={!Solve.configured?() and is_nil(@solve_note)}>Plate solving online needs an astrometry.net API key: set <code>NOVA_API_KEY</code> on the machine running the server (free at nova.astrometry.net).</.hint>
        </div>
      </.card>

      <.card :if={@site.set} title="Equatorial Mount">
        <.kv label="Polar axis altitude" value={"#{fmt(abs(@site.lat), 1)}° on the latitude scale"} />
        <.kv label="Aim at" value={if @site.lat >= 0, do: "True north: Polaris, about 0.7° off the pole", else: "True south: the south celestial pole (Sigma Octantis)"} />
        <.kv label="Sidereal time" value={hours(Astro.lst_deg(@now, @site.lon))} />
      </.card>

      <.card title="Hand Controller (NexStar)">
        <.hint :if={!@phone}>Open this page on the phone you set up with: its clock and time zone fill this in.</.hint>
        <%= if @phone do %>
          <% local = DateTime.add(@now, @phone.offset_min * 60, :second) %>
          <.kv label="Time" value={Calendar.strftime(local, "%H:%M:%S")} />
          <.kv label="Daylight saving" value={if @phone.dst, do: "Daylight Saving (on)", else: "Standard Time (off)"} />
          <.kv label="Time zone" value={"#{zone_hours(@phone.std_offset_min)} (#{@phone.tz})"} />
          <.kv label="Date" value={Calendar.strftime(local, "%m/%d/%Y")} />
          <.kv :if={@site.set} label="Latitude" value={dm(@site.lat, "North", "South")} />
          <.kv :if={@site.set} label="Longitude" value={dm(@site.lon, "East", "West")} />
        <% end %>
      </.card>

      <.card title="Time">
        <.kv label="UTC" value={Calendar.strftime(@now, "%Y-%m-%d %H:%M:%S")} />
        <.kv label="This machine" value={if Clock.synced?(), do: "Set by the network", else: "Not set by the network"} />
        <.kv :if={@phone} label="This phone" value={skew_words(@phone.skew_ms) <> " than this machine"} />
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp source_words(%{source: "phone", accuracy_m: acc, at: at}, now), do: "This phone, ±#{round(acc || 0)} m, #{ago(at, now)}"
  defp source_words(%{source: "typed", at: at}, now), do: "Typed, #{ago(at, now)}"
  defp source_words(%{source: "config"}, _), do: "The config file"
  defp source_words(_, _), do: "Set"

  defp ago(nil, _), do: "earlier"

  defp ago(at, now) do
    s = DateTime.diff(now, at)

    cond do
      s < 90 -> "just now"
      s < 5400 -> "#{div(s, 60)} min ago"
      s < 172_800 -> "#{div(s, 3600)} h ago"
      true -> Calendar.strftime(at, "%b %-d")
    end
  end

  defp skew_words(ms) when abs(ms) < 500, do: "Within half a second"
  defp skew_words(ms) when ms > 0, do: "#{Float.round(ms / 1000, 1)} s ahead"
  defp skew_words(ms), do: "#{Float.round(-ms / 1000, 1)} s behind"

  # hours from UTC the way a hand controller's time zone list reads: standard
  # time, daylight saving chosen separately
  defp zone_hours(min) do
    sign = if min < 0, do: "-", else: "+"
    h = div(abs(min), 60)
    m = rem(abs(min), 60)
    if m == 0, do: "UTC#{sign}#{h}", else: "UTC#{sign}#{h}:#{String.pad_leading("#{m}", 2, "0")}"
  end

  defp fmt(x, places), do: :erlang.float_to_binary(x / 1, decimals: places)

  defp dms(deg, pos, neg) do
    a = abs(deg)
    d = trunc(a)
    m = trunc((a - d) * 60)
    s = (a - d - m / 60) * 3600
    "#{d}° #{String.pad_leading("#{m}", 2, "0")}′ #{:erlang.float_to_binary(s, decimals: 1)}″ #{if deg >= 0, do: pos, else: neg}"
  end

  defp dm(deg, pos, neg) do
    a = abs(deg)
    d = trunc(a)
    m = round((a - d) * 60)
    {d, m} = if m == 60, do: {d + 1, 0}, else: {d, m}
    "#{d}° #{String.pad_leading("#{m}", 2, "0")}′ #{if deg >= 0, do: pos, else: neg}"
  end

  defp hours(deg) do
    h = deg / 15
    hh = trunc(h)
    mm = trunc((h - hh) * 60)
    "#{String.pad_leading("#{hh}", 2, "0")}h #{String.pad_leading("#{mm}", 2, "0")}m"
  end
end
