defmodule Controller.Nav do
  @moduledoc """
  Every page, once. Everything that lists pages draws from here, so a page
  added here is in all of them and they never disagree:

    * the sidebar on a wide screen and the page list on a phone's Home, both
      `Controller.Components.Menu.menu/1`;
    * Search (`Controller.Search`, ⌘K or a phone's search key);
    * which sidebar entry is marked while you're on a page (`current/1`).

  A page is a map: `title`, `path` (its one address: no page lives at two),
  `line` (what it's for, shown under the title where there's room), `doc`
  (its help), `icon` (`Controller.Components.Icons`), and `also`, other
  addresses that are this page (its own with a mount id, a page under it).
  Pages reached from another page rather than the sidebar (a camera's
  Settings) are in `under/0`, each naming its `parent`.

  Also an `on_mount` hook: it keeps `@current_path` on every page mounted by
  the router, so the sidebar can mark where you are.
  """
  use Controller, :verified_routes
  import Phoenix.LiveView, only: [attach_hook: 4]
  import Phoenix.Component, only: [assign: 3]

  @doc "A page entry. `opts`: `also:` other addresses that are this page."
  def page(title, path, line, doc, icon, opts \\ []) do
    %{title: title, path: path, line: line, doc: doc, icon: icon, also: Keyword.get(opts, :also, [])}
  end

  # ~p only works inside functions; this is a function that returns the list
  @doc "The sidebar: `[{group, what it's for, [page]}]`, in order."
  def groups do
    [
      # In the order of a night: get the mount onto the sky, pick something, move
      # to it, look; then the mount itself, and the machine underneath.
      {"Alignment", "Getting a mount that was set down anyhow onto the sky: where it stands, and where it points",
       [
         page("Start", ~p"/start", "One guided flow from plugging in to looking, done once three stars agree", ~p"/docs/start", "play", also: ["/setup"]),
         page("Site", ~p"/site", "Where the scope stands and what time it is: latitude for the mount, time for a hand controller", ~p"/docs/site", "compass"),
         page("Star Align", ~p"/controls/align", "Center a few stars; the software works out how the mount really sits", ~p"/docs/align", "star"),
         page("Align by Photo", ~p"/align/photo", "Photograph the eyepiece with a phone: the polar axis, which bolt to turn and how far", ~p"/docs/align-photo", "snap"),
         page("Optical Axes", ~p"/controls/watch/axes", "Experiment: turn each axis a little with the observatory camera watching, and find where it pivots", ~p"/docs/axes", "crosshair")
       ]},
      {"Sky", "What's up from here, and Go To",
       [
         page("Tonight", ~p"/tonight", "What's worth looking at right now, best first: whether it's clear of the trees, and for how long", ~p"/docs/sky", "moon"),
         page("Sky Map", ~p"/sky", "A map of the sky right now and your tree line; tap an object for Go To", ~p"/docs/sky", "globe", also: ["/object"])
       ]},
      {"Controls", "Ways to move the scope; each is an experiment in what feels right in the dark",
       [
         page("Axis Strips", ~p"/keypad", "One pull-to-speed strip per axis; the field keypad", ~p"/docs/keypad", "sliders"),
         page("Plain Keypad", ~p"/controls/dpad", "Four arrows and a rate row; the baseline", ~p"/docs/keypad", "dpad"),
         page("Nudge", ~p"/controls/nudge", "Tap to move an exact 1′, 5′, 30′ or 2°; for centering", ~p"/docs/nudge", "nudge"),
         page("Center", ~p"/controls/center", "The eyepiece as a touchpad: pull the way the view should go; for when your eye is on the eyepiece", ~p"/docs/center", "center"),
         page("Position", ~p"/controls/position", "Type an axis angle, go there; go home", ~p"/docs/position", "pin"),
         page("Game Controller", ~p"/input", "A USB pad read by the server: trigger is the dead-man, the ball is speed", ~p"/docs/devices", "gamepad"),
         page("Control Stack", ~p"/stack", "Every layer between a hand and the motors, live: which one is driving and what each corrects", ~p"/docs/stack", "layers")
       ]},
      # each camera's settings and frames are pages under it (reached from it,
      # and from Search), not entries here
      {"Cameras", "The camera in the telescope and the camera watching the observatory",
       [
         page("All Cameras", ~p"/cameras", "Every camera's latest picture, side by side", ~p"/docs/cameras", "cameras"),
         page("Telescope Camera", ~p"/cameras/telescope", "The camera in the focuser: what the telescope sees, and Find Where It's Pointing", ~p"/docs/scope-camera", "camera"),
         page("Focus", ~p"/cameras/telescope/focus", "Turn the focuser slowly and watch it get sharper or blurrier", ~p"/docs/scope-camera", "focus"),
         page("Observatory Camera", ~p"/cameras/observatory", "The camera watching the mount: the latest still, and live video", ~p"/docs/watch", "video")
       ]},
      {"Mount", "The mount as it stands, drawn live from its encoders",
       [
         page("Scope", ~p"/controls/scope", "The mount in 3-D, posed from the encoders", ~p"/docs/scope", "telescope"),
         page("Orb", ~p"/controls/orb", "The mount's geometry as a 3-D gizmo, live, with strips to turn each axis", ~p"/docs/orb", "orbit"),
         page("Eyepiece", ~p"/controls/eyepiece", "What the tube sees: the field, the target, the drift", ~p"/docs/eyepiece", "aperture")
       ]},
      {
        "System",
        "This machine: its hardware, its network, and what happened",
        # Devices first; then whatever this build's extensions add
        # (Controller.Extensions: the stamping Mac's Stamp a Box, a box's
        # Network and Bluetooth pages); then the pipes and the log
        [page("Devices", ~p"/devices", "Every piece of hardware, by what it's for: the mount, each camera, the game controller, power", ~p"/docs/devices", "plug")] ++
          Enum.map(Controller.Extensions.home("System"), &extension/1) ++
          [
            page("Queues", ~p"/queues", "Frames kept from the camera, step by step across the box and the Mac, and which step is slow", ~p"/docs/queues", "queue"),
            page("Events", ~p"/events", "What happened and who did it: every move, stop, star and stream, newest first", ~p"/docs/events", "activity")
          ]
      }
    ]
  end

  # an extension's line: `{title, path, line, doc}` or with an icon last
  defp extension({title, path, line, doc, icon}), do: page(title, path, line, doc, icon)
  defp extension({title, path, line, doc}), do: page(title, path, line, doc, "dot")

  @doc "Every sidebar page, in order."
  def pages, do: Enum.flat_map(groups(), &elem(&1, 2))

  @doc """
  Pages that live under a sidebar entry rather than in the sidebar: reached
  from their parent page, and from Search. Each is a page with a `parent`,
  the sidebar entry it belongs to, so the sidebar marks that while you're there.
  """
  def under do
    [
      under("Settings", ~p"/cameras/telescope/settings", "Exposure, gain, frames per picture, keeping frames, video", "Telescope Camera", "gear"),
      under("Frames", ~p"/cameras/telescope/frames", "The last pictures, each with what was known when it was taken", "Telescope Camera", "frames"),
      under("Settings", ~p"/cameras/observatory/settings", "Which camera, timed stills, video size and frame rate", "Observatory Camera", "gear"),
      under("Frames", ~p"/cameras/observatory/frames", "The last twenty minutes of stills, for looking back at a slew", "Observatory Camera", "frames"),
      under("Serial Ports", ~p"/devices/ports", "Every serial port this machine sees, and what answered on it", "Devices", "plug"),
      under("Boxes", ~p"/devices/boxes", "The boxes on this network, and connecting one by its node name", "Devices", "box")
    ]
  end

  defp under(title, path, line, parent, icon), do: title |> page(path, line, nil, icon) |> Map.put(:parent, parent)

  @doc """
  The sidebar entry for a path: the longest address of a page (or one of its
  `also`s) that is the path or one of its parents, so `/cameras/observatory/frames`
  marks Observatory Camera, not All Cameras. Home (`/`) matches only itself.
  """
  def current(nil), do: nil

  def current(path) do
    pages()
    |> Enum.flat_map(fn p -> for a <- [p.path | p.also], do: {a, p.path} end)
    |> Enum.filter(fn {a, _} -> a == path or (a != "/" and String.starts_with?(path, a <> "/")) end)
    |> Enum.max_by(fn {a, _} -> String.length(a) end, fn -> {nil, nil} end)
    |> elem(1)
  end

  # a LiveView rendered inside another (a step of the start flow) is not
  # mounted by the router and has no layout of its own: the page around it
  # keeps the path, and a child may not hook handle_params anyway
  def on_mount(:default, :not_mounted_at_router, _session, socket), do: {:cont, socket}

  def on_mount(:default, _params, session, socket) do
    telescopes = telescopes()

    socket =
      socket
      |> assign(:telescopes, telescopes)
      |> assign(:telescope, current(telescopes, session["telescope"]))
      |> attach_hook(:nav_path, :handle_params, fn params, uri, socket ->
        path = URI.parse(uri).path
        # an object opened from Tonight belongs to Tonight in the sidebar, not the Sky Map
        nav = if String.starts_with?(path, "/object/") and params["from"] == "tonight", do: ~p"/tonight"
        {:cont, socket |> Phoenix.Component.assign(:current_path, path) |> Phoenix.Component.assign(:nav_path, nav)}
      end)

    {:cont, socket}
  end

  @doc """
  Every telescope this machine can drive, for the switcher: its id, the box it
  is on (nil for this machine), and whether it is a simulator.
  """
  def telescopes do
    try do
      Mount.list()
    catch
      _, _ -> []
    end
    |> Enum.sort_by(&{Mount.simulated?(&1), &1.id})
    |> Enum.map(fn ref -> %{id: ref.id, where: where(ref.node), simulated: Mount.simulated?(ref)} end)
  end

  @doc "The viewer's telescope: the one they switched to, if it is still here, else the default."
  def current(telescopes, chosen) do
    ids = Enum.map(telescopes, & &1.id)
    id = if chosen in ids, do: chosen, else: Mount.default(ids)
    Enum.find(telescopes, &(&1.id == id))
  end

  defp where(node) when node == node(), do: nil
  defp where(node), do: node |> to_string() |> String.split("@") |> List.last() |> String.replace_suffix(".local", "")
end
