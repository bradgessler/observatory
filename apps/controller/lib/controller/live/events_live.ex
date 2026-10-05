defmodule Controller.EventsLive do
  @moduledoc """
  What happened, newest first, with who did it. The page to open when the
  camera shows the tube somewhere odd: was it the game controller, a phone,
  tracking, or nobody (moved by hand)? In-memory ring for now (#50 persists it).
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      Telescope.Events.subscribe()
      Settings.subscribe()
    end

    {:ok, assign(socket, page_title: "Events", night: Settings.get("night", false), filter: filter_from(params), events: Telescope.Events.recent(300))}
  end

  @impl true
  def handle_info({:event, e}, socket), do: {:noreply, assign(socket, events: Enum.take([e | socket.assigns.events], 200))}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("filter", %{"m" => "all"}, socket), do: {:noreply, assign(socket, filter: nil)}
  def handle_event("filter", %{"m" => m}, socket), do: {:noreply, assign(socket, filter: filter_from(%{"m" => m}))}

  defp filter_from(%{"m" => m}) when m in ~w(mount tracker input video lineup optical), do: String.to_existing_atom(m)
  defp filter_from(_), do: nil

  @impl true
  def render(assigns) do
    assigns = assign(assigns, shown: if(assigns.filter, do: Enum.filter(assigns.events, &(&1.module == assigns.filter)), else: assigns.events))

    ~H"""
    <.page id="events" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="System" />
        <.title>Events</.title>
        <.actions><.help href={~p"/docs/events"} label="events" /><.stop /></.actions>
      </:header>

      <.seg label="which events">
        <:opt :for={{lbl, m} <- [{"All", "all"}, {"Mount", "mount"}, {"Tracking", "tracker"}, {"Game Controller", "input"}, {"Video", "video"}]} on={to_string(@filter || "all") == m} click="filter" value={%{m: m}}>{lbl}</:opt>
      </.seg>

      <.hint :if={@shown == []}>Nothing yet. Every move, stop, star and video shows up here as it happens.</.hint>

      <ol class="events" aria-label="events, newest first">
        <li :for={e <- @shown}>
          <time datetime={Calendar.strftime(e.at, "%Y-%m-%dT%H:%M:%SZ")}>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
          <span class="ev-by">{e.by}</span>
          <span class="ev-what">{words(e)}</span>
        </li>
      </ol>
    </.page>
    """
  end

  defp words(%{module: :mount, name: :slew, data: d}), do: "#{d.id} · #{axis(d.axis)} at #{fmt(d.rate)}×#{if d[:hold], do: " (held)", else: ""}"
  defp words(%{module: :mount, name: :goto, data: d}), do: "#{d.id} · #{axis(d.axis)} by #{fmt(d.degrees)}°"
  defp words(%{module: :mount, name: :stop, data: d}), do: "#{d.id} · stop #{axis(d.axis)}#{if d[:instant], do: " now", else: ""}"
  defp words(%{module: :mount, name: :emergency_stop, data: d}), do: "#{d.id} · EMERGENCY STOP"
  defp words(%{module: :mount, name: :track, data: d}), do: "#{d.id} · tracking #{d.mode}"
  defp words(%{module: :mount, name: :set_home, data: d}), do: "#{d.id} · home set here"
  defp words(%{module: :mount, name: :connected, data: d}), do: "#{d.id} · connected · firmware #{d.firmware}"
  defp words(%{module: :mount, name: :link_lost, data: d}), do: "#{d.id} · LINK LOST (#{d.reason}) · driver restarting"
  defp words(%{module: :mount, name: :limit_stop, data: d}), do: "#{d.id} · #{axis(d.axis)} stopped at the soft limit (#{d.degrees}°)"
  defp words(%{module: :mount, name: :goto_failed, data: %{why: :motor_running} = d}), do: "#{d.id} · #{axis(d.axis)} Go To did not start: the axis was still moving"
  defp words(%{module: :mount, name: :goto_failed, data: d}), do: "#{d.id} · #{axis(d.axis)} Go To did not start: the mount took the command and did not move"
  defp words(%{module: :tracker, name: :start, data: d}), do: "Tracking #{d.target}"
  defp words(%{module: :tracker, name: :end, data: %{why: :lost, off_deg: off} = d}), do: "Gave up tracking #{d.target}: #{off}° off, too far to chase. The mount is not tracking"
  defp words(%{module: :tracker, name: :end, data: d}), do: "Stopped tracking #{d.target} (#{d.why})"
  defp words(%{module: :tracker, name: :rates, data: d}), do: "#{d.id} · RA #{d.ra}× · Dec #{d.dec}× on #{d.target}"
  defp words(%{module: :optical, name: :video_paused, data: d}), do: "Video paused · #{d.why}"
  defp words(%{module: :optical, name: :scan_cancelled, data: _}), do: "Scan cancelled"
  defp words(%{module: :optical, name: :scan_crashed, data: d}), do: "Scan crashed · #{d.reason}"
  defp words(%{module: :input, name: :ignored, data: d}), do: "Game controller: #{d.action} ignored · #{d.why}"
  defp words(%{module: :input, name: :buttons, data: d}), do: "Game controller: buttons #{values(d.pressed)} · hat #{plain(d.hat)} · axes #{values(d.axes)} · raw #{d.raw}#{if d.armed, do: "", else: " · off"}"
  defp words(%{module: :input, name: :stale, data: d}), do: "Game controller: report #{d.age_ms} ms old, dropped"
  defp words(%{module: :input, name: :trigger, data: d}), do: "Game controller: trigger squeezed · ball at #{values(d[:head] || d[:center])}#{if d.armed, do: "", else: " · off"}"
  defp words(%{module: :input, name: :armed, data: d}), do: "Game controller on · moves #{d.target || "no mount yet"}"
  defp words(%{module: :input, name: :off, data: d}), do: "Game controller off · #{d.why}"
  defp words(%{module: :lineup, name: :reset, data: d}), do: "#{d.id} · alignment reset: #{d.why}"
  defp words(%{module: :lineup, name: :star, data: d}), do: "Alignment star: #{d.name} at RA #{fmt(d.theta_ra)}° Dec #{fmt(d.theta_dec)}°"
  defp words(%{module: :optical, name: :axes_found, data: d}), do: "#{d.id} · axes scanned · RA #{d.ra} · Dec #{d.dec}"
  defp words(%{module: :optical, name: :sweep_done, data: d}), do: "#{d.id} · axes swept · RA #{d.ra} · Dec #{d.dec} · #{d.between}° between"
  defp words(%{module: :video, name: :start, data: d}), do: "Video #{d.quality} · #{d.encoder} · #{d.fps} fps"
  defp words(%{module: :video, name: :stop, data: d}), do: "Video stopped (#{d.quality})"
  defp words(%{module: :video, name: :frozen, data: d}), do: "Camera froze on one frame (#{d.quality}) · encoder restarted"
  defp words(%{module: :input, name: :centered, data: d}), do: "#{d.mount} · Centered from the game controller"
  defp words(%{module: :mount, name: :stall, data: d}), do: "#{d.id} · #{axis(d.axis)} STALLED: moved #{fmt(d.moved_deg)}° of #{fmt(d.expected_deg)}° · both axes stopped"
  defp words(%{module: :mount, name: :power_on, data: d}), do: "#{d.id} · switched on: the axes count from where it stands"
  defp words(%{module: :lineup, name: :power_on, data: d}), do: "#{d.id} · alignment reset: #{d.why}"
  defp words(%{module: :center, name: :centered, data: d}), do: "#{d.mount} · Centered"
  defp words(%{module: :center, name: :flipped, data: d}), do: "Eyepiece view: #{if d.pair == "down", do: "up/down", else: "left/right"} flipped"
  defp words(%{module: :center, name: :turned}), do: "Eyepiece view: up/down and left/right swapped"
  defp words(%{module: :scope_camera, name: :found, data: d}), do: "Telescope camera found · #{d.name}"
  defp words(%{module: :scope_camera, name: :gone}), do: "Telescope camera unplugged"
  defp words(%{module: :auto_align, name: :done, data: d}), do: "#{d.id} · Auto Align #{if d.ok, do: "done", else: "gave up"} · #{d.solved} of #{d.pictures} frames plate solved"
  defp words(%{module: :plates, name: :added, data: d}), do: "#{d.id} · photo #{d.n} taken#{if d[:moving], do: " while moving", else: ""}"
  defp words(%{module: :plates, name: :solved, data: d}), do: "#{d.id} · photo #{d.n} #{if d.ok, do: "plate solved", else: "not solved"}"
  defp words(%{module: :plates, name: :used, data: d}), do: "#{d.id} · alignment from #{d.n} photos in use"
  defp words(%{module: :power, name: :low, data: d}), do: "Power low · dip #{d.dips} since the box started"
  defp words(%{module: :power, name: :normal}), do: "Power back to normal"
  defp words(%{module: :move, name: :flip_home, data: d}), do: "#{d.id} · meridian flip to #{d.target}: stopped at the home position to check the way is clear"
  defp words(%{module: :move, name: :flip_on, data: d}), do: "#{d.id} · meridian flip: on to #{d.target}"
  defp words(%{module: :system, name: :clock_set, data: d}), do: "Clock set from a phone · #{short_time(d.from)} → #{short_time(d.to)} UTC"

  # anything not worded above: its names in plain words, and any simple values
  defp words(e) do
    details = for {k, v} <- Map.to_list(e.data || %{}), (w = plain(v)) != nil, do: "#{plain(k)} #{w}"
    Enum.join([sentence("#{plain(e.module)} #{plain(e.name)}") | details], " · ")
  end

  defp axis(:ra), do: "RA"
  defp axis(:dec), do: "Dec"
  defp axis(:both), do: "both axes"
  defp axis(other), do: plain(other)

  # a value as words, or nil for anything that isn't one (maps, pids, lists of things)
  defp plain(nil), do: nil
  defp plain(v) when is_atom(v), do: v |> Atom.to_string() |> String.replace("_", " ")
  defp plain(v) when is_binary(v), do: v
  defp plain(v) when is_integer(v), do: Integer.to_string(v)
  defp plain(v) when is_float(v), do: fmt(v)
  defp plain(_), do: nil

  defp values([]), do: "none"
  defp values(l) when is_list(l), do: Enum.map_join(l, ", ", &(plain(&1) || "?"))
  defp values(other), do: plain(other) || "none"

  defp short_time(iso) when is_binary(iso), do: String.slice(iso, 11, 8)
  defp short_time(_), do: "?"

  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 2)
  defp fmt(x), do: to_string(x)
end
