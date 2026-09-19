defmodule Controller.EventsLive do
  @moduledoc """
  What happened, newest first, with who did it. The page to open when the
  camera shows the tube somewhere odd: was it the pad, a phone, the tracker,
  or nobody (moved by hand)? In-memory ring for now (#50 persists it).
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Telescope.Events.subscribe()
      Settings.subscribe()
    end

    {:ok, assign(socket, night: Settings.get("night", false), filter: nil, events: Telescope.Events.recent(200))}
  end

  @impl true
  def handle_info({:event, e}, socket), do: {:noreply, assign(socket, events: Enum.take([e | socket.assigns.events], 200))}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("filter", %{"m" => "all"}, socket), do: {:noreply, assign(socket, filter: nil)}
  def handle_event("filter", %{"m" => m}, socket), do: {:noreply, assign(socket, filter: String.to_existing_atom(m))}

  @impl true
  def render(assigns) do
    assigns = assign(assigns, shown: if(assigns.filter, do: Enum.filter(assigns.events, &(&1.module == assigns.filter)), else: assigns.events))

    ~H"""
    <.page id="events" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" />
        <.title>Events</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <div class="seg seg-4" role="radiogroup" aria-label="which events">
        <button :for={{lbl, m} <- [{"All", "all"}, {"Mount", "mount"}, {"Tracker", "tracker"}, {"Video", "video"}]} class={["seg-opt", to_string(@filter || "all") == m && "on"]} phx-click="filter" phx-value-m={m} role="radio" aria-checked={to_string(to_string(@filter || "all") == m)}>{lbl}</button>
      </div>

      <.hint :if={@shown == []}>Nothing yet. Every move, stop, star and stream shows up here as it happens.</.hint>

      <ol class="events">
        <li :for={e <- @shown}>
          <time>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
          <span class="ev-by">{e.by}</span>
          <span class="ev-what">{words(e)}</span>
        </li>
      </ol>
    </.page>
    """
  end

  defp words(%{module: :mount, name: :slew, data: d}), do: "#{d.id} · #{d.axis} at #{fmt(d.rate)}×#{if d[:hold], do: " (held)", else: ""}"
  defp words(%{module: :mount, name: :goto, data: d}), do: "#{d.id} · #{d.axis} by #{fmt(d.degrees)}°"
  defp words(%{module: :mount, name: :stop, data: d}), do: "#{d.id} · stop #{d.axis}#{if d[:instant], do: " now", else: ""}"
  defp words(%{module: :mount, name: :emergency_stop, data: d}), do: "#{d.id} · EMERGENCY STOP"
  defp words(%{module: :mount, name: :track, data: d}), do: "#{d.id} · tracking #{d.mode}"
  defp words(%{module: :mount, name: :set_home, data: d}), do: "#{d.id} · home set here"
  defp words(%{module: :mount, name: :connected, data: d}), do: "#{d.id} · connected · firmware #{d.firmware}"
  defp words(%{module: :mount, name: :link_lost, data: d}), do: "#{d.id} · LINK LOST (#{d.reason}) · driver restarting"
  defp words(%{module: :mount, name: :limit_stop, data: d}), do: "#{d.id} · #{d.axis} stopped at the soft limit (#{d.degrees}°)"
  defp words(%{module: :tracker, name: :start, data: d}), do: "holding #{d.target}"
  defp words(%{module: :tracker, name: :end, data: d}), do: "stopped holding #{d.target} (#{d.why})"
  defp words(%{module: :lineup, name: :star, data: d}), do: "line-up star: #{d.name} at RA #{fmt(d.theta_ra)}° Dec #{fmt(d.theta_dec)}°"
  defp words(%{module: :optical, name: :axes_found, data: d}), do: "#{d.id} · axes scanned · RA #{d.ra} · Dec #{d.dec}"
  defp words(%{module: :video, name: :start, data: d}), do: "video #{d.quality} · #{d.encoder} · #{d.fps} fps"
  defp words(%{module: :video, name: :stop, data: d}), do: "video stopped (#{d.quality})"
  defp words(e), do: "#{e.module} · #{e.name} · #{inspect(e.data)}"

  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 2)
  defp fmt(x), do: to_string(x)
end
