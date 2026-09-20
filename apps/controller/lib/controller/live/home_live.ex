defmodule Controller.HomeLive do
  @moduledoc """
  The front door: a short, grouped list of everything you can open, each a
  button with a name and one line saying what it is. Controls, the star alignment
  and sky ("Star Lock"), the camera, and the plumbing. The bench (where the
  experiments live side by side) is one of the entries, not the front door.

  Keep this list honest: if something is here it works; if it stops being
  useful it leaves. The one-liners double as the reason each thing exists.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  # ~p only works inside functions; this is a function that returns the list
  defp groups do
    [
    {"Star Lock",
     "Getting a mount that was set down anyhow onto the sky, and keeping it there",
     [
       {"Start", ~p"/start", "Experiment: one guided flow from plug in to looking, that locks once three stars agree", ~p"/docs/start"},
       {"Star Align", ~p"/bench/align", "Name a few stars; the software works out how the mount really sits", ~p"/docs/align"},
       {"Sky", ~p"/bench/sky", "The sky right now, tonight's targets, your tree line; tap and slew", ~p"/docs/sky"},
       {"Orb", ~p"/bench/orb", "The mount's geometry as a 3-D gizmo, live, with strips to turn each axis", ~p"/docs/orb"},
       {"Optical Axes", ~p"/controls/watch/axes", "Experiment: turn each axis a little with the camera watching, find where it pivots in the picture", ~p"/docs/axes"}
     ]},
    {"Controls",
     "Ways to move the scope; each is an experiment in what feels right in the dark",
     [
       {"Axis Strips", ~p"/bench/strips", "One pull-to-speed strip per axis; the field keypad", ~p"/docs/keypad"},
       {"Plain Keypad", ~p"/bench/dpad", "Four arrows and a rate row; the baseline", ~p"/docs/keypad"},
       {"Nudge", ~p"/bench/nudge", "Tap to move an exact 1′, 5′, 30′ or 2°; for centring", ~p"/docs/nudge"},
       {"Tilt", ~p"/bench/tilt", "Hold the button, tilt the phone; for when your eye is on the eyepiece", ~p"/docs/tilt"},
       {"Position", ~p"/bench/position", "Type an axis angle, go there; go home", ~p"/docs/position"},
       {"Game Controller", ~p"/bench/gamepad", "A USB pad read by the server: trigger is the dead-man, the ball is speed", ~p"/docs/devices"}
     ]},
    {"Watch",
     "Eyes on the hardware from anywhere",
     [
       {"Watch", ~p"/controls/watch", "The latest still, kept fresh; press Play for live video", ~p"/docs/watch"},
       {"Recent Frames", ~p"/controls/watch/frames", "The last twenty minutes of stills, for looking back at a slew", ~p"/docs/watch"},
       {"Camera", ~p"/controls/watch/camera", "Which camera, timed stills, video size and frame rate", ~p"/docs/watch"}
     ]},
    {"Plumbing",
     "What is plugged in and how to reach this machine",
     [
       {"Devices", ~p"/devices", "The telescope cable, the mount answering or not, the addresses", ~p"/docs/devices"},
       {"Events", ~p"/events", "What happened and who did it: every move, stop, star and stream, newest first", ~p"/docs/events"},
       {"Bench", ~p"/bench", "Every surface side by side with the live scope state; where new things get tried", ~p"/docs/bench"}
     ]}
    ]
  end

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: Settings.subscribe()
    {:ok, assign(socket, page_title: "Everything", night: Settings.get("night", false), groups: groups(), mounts: mounts())}
  end

  defp mounts do
    try do
      Mount.list() |> Enum.map(& &1.id)
    catch
      :exit, _ -> []
    end
  end

  @impl true
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("night", _, socket) do
    v = !socket.assigns.night
    Settings.put("night", v)
    {:noreply, assign(socket, night: v)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="home" night={@night}>
      <:header>
        <span class="home-brand">Observatory</span>
        <.title>Home</.title>
        <.actions><button class="ghost" phx-click="night" aria-label="night mode" aria-pressed={to_string(@night)}>◐</button></.actions>
      </:header>

      <p class="home-lede">
        {case @mounts do
          [] -> "No mount connected yet: plug the EQDIR cable into this machine."
          [one] -> "Talking to #{one}."
          many -> "Talking to #{Enum.join(many, ", ")}."
        end}
      </p>

      <section :for={{name, blurb, items} <- @groups} class="home-group">
        <h2>{name}</h2>
        <p class="dim">{blurb}</p>
        <ul class="home-list" role="list">
          <li :for={{title, path, sub, _doc} <- items} class="home-item">
            <.link navigate={path} class="home-btn">
              <strong>{title}</strong>
              <span>{sub}</span>
            </.link>
          </li>
        </ul>
      </section>
    </.page>
    """
  end
end
