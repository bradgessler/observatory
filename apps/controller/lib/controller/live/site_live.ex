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
  alias Controller.Sky.{Astro, Pointing}

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      :timer.send_interval(1_000, :tick)
    end

    {:ok,
     socket
     |> assign(page_title: "Site", night: Settings.get("night", false), notice: nil, phone: nil)
     |> assign(now: DateTime.utc_now(), site: site())}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}
  def handle_info({:settings, "site", _}, socket), do: {:noreply, assign(socket, site: site())}
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

      {:noreply, assign(socket, site: site(), notice: if(from_phone?, do: "Site set from this phone", else: "Site saved"))}
    else
      _ -> {:noreply, assign(socket, notice: "Not saved: latitude is -90 to 90, longitude -180 to 180")}
    end
  end

  def handle_event("site_error", %{"reason" => r}, socket), do: {:noreply, assign(socket, notice: Controller.Site.location_error(r))}

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
      set: saved != %{},
      accuracy_m: saved["accuracy_m"],
      source: saved["source"],
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
        <.title>Site</.title>
        <.actions><.help href={~p"/docs/site"} label="site" /><.stop /></.actions>
      </:header>

      <div id="phone-clock" phx-hook="Clock" hidden></div>

      <.card title="Latitude and Longitude">
        <div :if={@site.set} class="site-coords" role="status">
          <p class="site-big">{dms(@site.lat, "N", "S")}<br />{dms(@site.lon, "E", "W")}</p>
          <.kv label="Decimal" value={"#{fmt(@site.lat, 5)}, #{fmt(@site.lon, 5)}"} />
          <.kv label="From" value={source_words(@site, @now)} />
        </div>
        <.hint :if={!@site.set}>Not set. Pointing assumes latitude 0 until it is.</.hint>
        <.row>
          <button id="use-phone-location" class="btn btn-primary" phx-hook="Geo">Use This Phone's Location</button>
        </.row>
        <form phx-submit="site" class="site-typed" aria-label="type the site">
          <label>Latitude <input name="lat" type="text" inputmode="decimal" class="field" value={if @site.set, do: fmt(@site.lat, 5)} /></label>
          <label>Longitude <input name="lon" type="text" inputmode="decimal" class="field" value={if @site.set, do: fmt(@site.lon, 5)} /></label>
          <.btn type="submit">Save</.btn>
        </form>
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
