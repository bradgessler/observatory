defmodule Controller.Nav do
  @moduledoc """
  Every page, grouped, once. The desktop sidebar (`Controller.Layouts.shell/1`)
  and the phone's Home screen both draw from `groups/0`, so a page added here
  shows up in both and the two never disagree.

  Each entry is `{title, path, one line, doc}`. The one line is shown on Home,
  where there is room for it; the sidebar shows the title alone.

  Also an `on_mount` hook: it keeps `@current_path` on every page mounted by
  the router, so the sidebar can mark where you are.
  """
  use Controller, :verified_routes
  import Phoenix.LiveView, only: [attach_hook: 4]
  import Phoenix.Component, only: [assign: 3]

  # ~p only works inside functions; this is a function that returns the list
  def groups do
    [
      {"Star Lock", "Getting a mount that was set down anyhow onto the sky, and keeping it there",
       [
         {"Start", ~p"/start",
          "Experiment: one guided flow from plug in to looking, that locks once three stars agree",
          ~p"/docs/start"},
         {"Star Align", ~p"/bench/align",
          "Name a few stars; the software works out how the mount really sits", ~p"/docs/align"},
         {"Sky", ~p"/bench/sky",
          "The sky right now, tonight's targets, your tree line; tap and slew", ~p"/docs/sky"},
         {"Eyepiece", ~p"/bench/eyepiece", "What the tube sees: the field, the target, the drift",
          ~p"/docs/eyepiece"},
         {"Scope", ~p"/bench/scope", "The mount as a picture, posed from the encoders",
          ~p"/docs/scope"},
         {"Orb", ~p"/bench/orb",
          "The mount's geometry as a 3-D gizmo, live, with strips to turn each axis",
          ~p"/docs/orb"},
         {"Optical Axes", ~p"/controls/watch/axes",
          "Experiment: turn each axis a little with the camera watching, find where it pivots in the picture",
          ~p"/docs/axes"}
       ]},
      {"Controls",
       "Ways to move the scope; each is an experiment in what feels right in the dark",
       [
         {"Axis Strips", ~p"/bench/strips", "One pull-to-speed strip per axis; the field keypad",
          ~p"/docs/keypad"},
         {"Plain Keypad", ~p"/bench/dpad", "Four arrows and a rate row; the baseline",
          ~p"/docs/keypad"},
         {"Nudge", ~p"/bench/nudge", "Tap to move an exact 1′, 5′, 30′ or 2°; for centring",
          ~p"/docs/nudge"},
         {"Tilt", ~p"/bench/tilt",
          "Hold the button, tilt the phone; for when your eye is on the eyepiece",
          ~p"/docs/tilt"},
         {"Position", ~p"/bench/position", "Type an axis angle, go there; go home",
          ~p"/docs/position"},
         {"Game Controller", ~p"/bench/gamepad",
          "A USB pad read by the server: trigger is the dead-man, the ball is speed",
          ~p"/docs/devices"}
       ]},
      {"Watch", "Eyes on the hardware from anywhere",
       [
         {"Watch", ~p"/controls/watch", "The latest still, kept fresh; press Play for live video",
          ~p"/docs/watch"},
         {"Recent Frames", ~p"/controls/watch/frames",
          "The last twenty minutes of stills, for looking back at a slew", ~p"/docs/watch"},
         {"Camera", ~p"/controls/watch/camera",
          "Which camera, timed stills, video size and frame rate", ~p"/docs/watch"}
       ]},
      {
        "Plumbing",
        "What is plugged in and how to reach this machine",
        # plus whatever this build's extensions add (Controller.Extensions): the
        # stamping Mac's Stamp a Box, a box's Network page
        Controller.Extensions.home("Plumbing") ++
          [
            {"Devices", ~p"/devices",
             "The telescope cable, the mount answering or not, the addresses", ~p"/docs/devices"},
            {"Events", ~p"/events",
             "What happened and who did it: every move, stop, star and stream, newest first",
             ~p"/docs/events"},
            {"Bench", ~p"/bench",
             "Every surface side by side with the live scope state; where new things get tried",
             ~p"/docs/bench"}
          ]
      }
    ]
  end

  @doc """
  The entry for a path: the longest listed path that is the path or one of its
  parents, so `/controls/watch/frames` marks Recent Frames and not Watch. Home
  (`/`) matches only itself.
  """
  def current(nil), do: nil

  def current(path) do
    groups()
    |> Enum.flat_map(fn {_, _, items} -> Enum.map(items, &elem(&1, 1)) end)
    |> Enum.filter(&(&1 == path or (&1 != "/" and String.starts_with?(path, &1 <> "/"))))
    |> Enum.max_by(&String.length/1, fn -> nil end)
  end

  # a LiveView rendered inside another (the bench, the start flow) is not
  # mounted by the router and has no layout of its own: the page around it
  # keeps the path, and a child may not hook handle_params anyway
  def on_mount(:default, :not_mounted_at_router, _session, socket), do: {:cont, socket}

  def on_mount(:default, _params, _session, socket) do
    {:cont,
     attach_hook(socket, :nav_path, :handle_params, fn _params, uri, socket ->
       {:cont, assign(socket, :current_path, URI.parse(uri).path)}
     end)}
  end
end
