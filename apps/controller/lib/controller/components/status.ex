defmodule Controller.Components.Status do
  @moduledoc """
  The telescope's state, always visible: which mount, answering or not, RA/Dec
  axis degrees with motion dots, tracking, homed. Same strip on every surface
  so flipping between controls never loses the picture.
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
        <span class="ss-axis"><b>RA</b> {deg(@snap.axes.ra.degrees)}<Controller.Components.UI.lamp on={@snap.axes.ra.running} /></span>
        <span class="ss-axis"><b>Dec</b> {deg(@snap.axes.dec.degrees)}<Controller.Components.UI.lamp on={@snap.axes.dec.running} /></span>
        <% model_track = Controller.Sky.Tracker.status(@id) %>
        <span class={["ss-badge", (@snap.tracking != :off or model_track) && "on"]}>
          {cond do
            model_track && model_track.paused == :goto -> "slewing · #{model_track.name}"
            model_track && model_track.paused -> "tracking · paused"
            model_track -> "tracking · #{model_track.name}"
            @snap.tracking != :off -> "tracking"
            true -> "not tracking"
          end}
        </span>
        <span class={["ss-badge", @snap.homed && "on"]}>{if @snap.homed, do: "zeroed", else: "not zeroed"}</span>
        <span :if={@snap.id == "sim"} class="ss-badge warn">simulator</span>
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

  defp deg(_), do: "—"
end
