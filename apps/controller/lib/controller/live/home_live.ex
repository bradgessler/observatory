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


  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      Telescope.subscribe("tracker")
      send(self(), :rescan)
    end

    {:ok,
     socket
     |> assign(page_title: "Home", night: Settings.get("night", false), groups: Controller.Nav.groups(), mounts: [], snaps: %{}, holding: %{}, subscribed: MapSet.new())
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
