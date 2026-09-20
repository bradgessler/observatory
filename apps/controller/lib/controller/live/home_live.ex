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
       {"Eyepiece", ~p"/bench/eyepiece", "What the tube sees: the field, the target, the drift", ~p"/docs/eyepiece"},
       {"Scope", ~p"/bench/scope", "The mount as a picture, posed from the encoders", ~p"/docs/scope"},
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
       {"Stamp a Box", ~p"/provision", "Put a card in, choose what the box is for, and write a bootable Observatory onto it", ~p"/docs/provision"},
       {"Devices", ~p"/devices", "The telescope cable, the mount answering or not, the addresses", ~p"/docs/devices"},
       {"Events", ~p"/events", "What happened and who did it: every move, stop, star and stream, newest first", ~p"/docs/events"},
       {"Bench", ~p"/bench", "Every surface side by side with the live scope state; where new things get tried", ~p"/docs/bench"}
     ]}
    ]
  end

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      Telescope.subscribe("tracker")
      send(self(), :rescan)
    end

    {:ok,
     socket
     |> assign(page_title: "Home", night: Settings.get("night", false), groups: groups(), mounts: [], snaps: %{}, holding: %{}, subscribed: MapSet.new())
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket), do: {:noreply, assign(socket, snaps: Map.put(socket.assigns.snaps, snap.id, snap))}

  def handle_info({:tracker, id, status}, socket) do
    {:noreply, assign(socket, holding: Map.put(socket.assigns.holding, id, status && status.name))}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  # One badge per mount, live. Subscribe once per id, ever: a driver that
  # restarts must not double the 250 ms traffic into this page.
  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    snaps = Map.new(refs, fn {id, ref} -> {id, socket.assigns.snaps[id] || safe(fn -> Mount.snapshot(ref) end)} end)
    holding = Map.new(refs, fn {id, _} -> {id, socket.assigns.holding[id] || holding_of(id)} end)
    assign(socket, mounts: refs |> Map.keys() |> Enum.sort(), snaps: snaps, holding: holding, subscribed: subscribed)
  end

  defp holding_of(id) do
    case safe(fn -> Controller.Sky.Tracker.status(id) end) do
      %{name: name} -> name
      _ -> nil
    end
  end

  defp pose_of(nil), do: nil

  defp pose_of(snap) do
    ctx = Controller.Sky.Pointing.context(DateTime.utc_now(), snap.id)
    Controller.Components.Scope.pose_from(snap, ctx, tracker: Controller.Sky.Tracker.status(snap.id))
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end

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

      <%!-- the scopes themselves, drawn and live, before any list of pages --%>
      <section :if={@mounts != []} class="home-scopes" aria-label="Scopes">
        <Controller.Components.ScopeBadge.badge
          :for={id <- @mounts}
          id={id}
          snap={@snaps[id]}
          pose={pose_of(@snaps[id])}
          holding={@holding[id]}
          navigate={~p"/setup/#{id}"}
        />
      </section>

      <p :if={@mounts == []} class="home-lede">
        No mount connected yet: plug the telescope cable into this machine.
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
