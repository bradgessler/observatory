defmodule Controller.Source do
  @moduledoc "Tags each LiveView process with a short name so the events log can say which page sent a command."
  import Phoenix.Component, only: []

  def on_mount(:default, _params, _session, socket) do
    name = socket.view |> Module.split() |> List.last() |> String.replace_suffix("Live", "")
    # modules keep their names; the log uses the words on the page
    name = Map.get(%{"Lineup" => "Star Align", "Start" => "Start", "Dpad" => "Keypad", "Mount" => "Axis Strips"}, name, name)
    Telescope.Events.tag("page · #{name}")
    {:cont, socket}
  end
end
