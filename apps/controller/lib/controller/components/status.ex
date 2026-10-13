defmodule Controller.Components.Status do
  @moduledoc """
  One mount's detail in a line, on its own page (Telescope > Now): answering
  or not, each axis's angle with a lamp while it turns, tracking, home set,
  simulator. What the telescope is doing and where it points is said once,
  by the bar at the top of every page (`Controller.ScopeNow`); this is the
  line under it for the things the bar has no room for. It opens Setup.
  """
  use Phoenix.Component
  use Controller, :verified_routes

  attr :snap, :map, default: nil
  attr :id, :string, default: nil
  attr :compact, :boolean, default: false

  def status(assigns) do
    ~H"""
    <.link navigate={if @id, do: ~p"/setup/#{@id}", else: ~p"/devices"} class={["scope-status", @compact && "compact"]}>
      <%= if @snap && @snap.connected do %>
        <span class="ss-id">{@id}</span>
        <span class="ss-axis"><b>RA axis</b> {deg(@snap.axes.ra.degrees)}<Controller.Components.UI.lamp on={@snap.axes.ra.running} /></span>
        <span class="ss-axis"><b>Dec axis</b> {deg(@snap.axes.dec.degrees)}<Controller.Components.UI.lamp on={@snap.axes.dec.running} /></span>
        <% model_track = Controller.Sky.Tracker.status(@id) %>
        <span class={["ss-badge", (@snap.tracking != :off or model_track) && "on"]}>
          {cond do
            model_track && model_track.paused == :goto -> "Slewing · #{model_track.name}"
            model_track && model_track.paused -> "Tracking · paused"
            model_track -> "Tracking · #{model_track.name}"
            @snap.tracking != :off -> "Tracking"
            true -> "Not tracking"
          end}
        </span>
        <span class={["ss-badge", @snap.homed && "on"]}>{if @snap.homed, do: "home set", else: "home not set"}</span>
        <span :if={Mount.simulated?(@snap.id)} class="ss-badge">Simulator</span>
      <% else %>
        <span class="ss-id">{@id || "no mount"}</span>
        <span class="ss-badge warn">{if @snap, do: "not answering", else: "not connected"}</span>
      <% end %>
    </.link>
    """
  end

  defp deg(d) when is_number(d) do
    sign = if d < 0, do: "−", else: "+"
    a = abs(d)
    "#{sign}#{trunc(a)}°#{:erlang.float_to_binary((a - trunc(a)) * 60, decimals: 0) |> String.pad_leading(2, "0")}′"
  end

  defp deg(_), do: Controller.Words.none()
end
