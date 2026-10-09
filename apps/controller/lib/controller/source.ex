defmodule Controller.Source do
  @moduledoc "Tags each LiveView process with a short name so the events log can say which page sent a command."
  import Phoenix.Component, only: []

  # module name → the page's name in the sidebar, where the two differ
  @names %{
    "Lineup" => "Align by Stars",
    "AlignPhoto" => "Align by Phone Photo",
    "Axes" => "Optical Axes",
    "Dpad" => "Plain Keypad",
    "Mount" => "Axis Strips",
    "Input" => "Game Controller",
    "Stack" => "Control Stack",
    "Sky" => "Sky Map",
    "Cameras" => "All Cameras",
    "ScopeCamera" => "Telescope Camera",
    "ScopeCameraFocus" => "Focus",
    "ScopeCameraSettings" => "Telescope Camera · Settings",
    "ScopeCameraFrames" => "Telescope Camera · Frames",
    "Watch" => "Observatory Camera",
    "Camera" => "Observatory Camera · Settings",
    "Frames" => "Observatory Camera · Frames",
    "Ports" => "Serial Ports"
  }

  def on_mount(:default, _params, _session, socket) do
    name = socket.view |> Module.split() |> List.last() |> String.replace_suffix("Live", "")
    # modules keep their names; the log uses the words on the page
    name = Map.get(@names, name, name)
    Telescope.Events.tag("page · #{name}")
    {:cont, socket}
  end
end
