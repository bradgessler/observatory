defmodule Controller.Extensions do
  @moduledoc """
  Pages other apps plug into the controller, chosen per build.

  The controller is the observatory's core UI, and it depends on none of the
  apps that extend it. Each build names the ones it carries
  (`config :controller, :extensions`), and the router and home page are
  composed from that list. The Mac that stamps cards adds Stamp a Box (from `stamp`); a
  stamped box adds its Network page and captive portal (from `firmware`). An
  extension a build does not list is not compiled into it, not routed, and not
  linked: it is simply not in that image.

  Each extension is a map of module names, never calls: extensions depend on
  the controller, so the controller cannot call into them while it compiles.

      %{
        # behind the browser pipeline, ahead of the controller's own routes
        routes: [{:live, "/network", Firmware.Web.NetworkLive, :index}],
        # no pipeline at all (a phone's captive-portal check has no session)
        bare: [{:get, "/generate_204", Firmware.Web.Captive, :redirect}],
        # lines on the home page, by group
        home: [{"Plumbing", {"Network", "/network", "The Wi-Fi radio", "/docs/network"}}]
      }
  """

  @extensions Application.compile_env(:controller, :extensions, [])

  def all, do: @extensions
  def routes, do: Enum.flat_map(@extensions, &Map.get(&1, :routes, []))
  def bare, do: Enum.flat_map(@extensions, &Map.get(&1, :bare, []))
  def home(group), do: for(ext <- @extensions, {^group, entry} <- Map.get(ext, :home, []), do: entry)
end
