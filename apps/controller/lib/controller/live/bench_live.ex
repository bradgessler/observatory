defmodule Controller.BenchLive do
  @moduledoc """
  The bench: one place to try every control surface against the same
  telescope. Sidebar on a laptop, tabs on a phone; the telescope's state is
  always at the top; the chosen surface renders below as a nested LiveView.
  Not the field UI — where we play.
  """
  use Controller, :live_view
  import Controller.Components.Status

  alias Controller.Settings

  @surfaces [
    {"strips", "Axis strips", Controller.MountLive, "one pull-to-speed strip per mount axis; the field keypad"},
    {"dpad", "Plain keypad", Controller.DpadLive, "four arrows and a rate row; the boring one"},
    {"orb", "Orb", Controller.OrbLive, "the equatorial geometry as a 3-D gizmo, with analog strips"},
    {"gamepad", "Game controller", Controller.InputLive, "a USB pad read by the server"},
    {"sky", "Sky", Controller.SkyLive, "map, tonight's targets, horizon"}
  ]

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
    end

    {:ok,
     socket
     |> assign(night: Settings.get("night", false), refs: %{}, selected: params["mount"], snap: nil, surface: nil)
     |> rescan()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    surface = if Enum.any?(@surfaces, fn {k, _, _, _} -> k == params["surface"] end), do: params["surface"], else: "strips"
    {:noreply, assign(socket, surface: surface, selected: params["mount"] || socket.assigns.selected)}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    assign(socket, refs: refs, selected: selected, snap: snap)
  end

  @impl true
  def handle_event("night", _, socket) do
    v = !socket.assigns.night
    Settings.put("night", v)
    {:noreply, assign(socket, night: v)}
  end

  @impl true
  def render(assigns) do
    assigns = assign(assigns, surfaces: @surfaces, current: Enum.find(@surfaces, fn {k, _, _, _} -> k == assigns.surface end))

    ~H"""
    <main class={["bench", @night && "night"]} id="bench">
      <header class="bench-head">
        <span class="bench-brand">bench</span>
        <.status snap={@snap} id={@selected} compact />
        <span class="hdr-actions">
          <.link navigate={~p"/devices"} class="ghost" aria-label="devices">⚙</.link>
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
        </span>
      </header>

      <nav class="bench-nav" aria-label="control surfaces">
        <.link :for={{key, name, _mod, blurb} <- @surfaces} patch={~p"/bench/#{key}?#{[mount: @selected]}"} class={["bench-tab", key == @surface && "on"]}>
          <strong>{name}</strong><span>{blurb}</span>
        </.link>
      </nav>

      <section class="bench-stage">
        <%= if @current do %>
          <% {key, _name, mod, _} = @current %>
          <%= live_render(@socket, mod, id: "surface-#{key}-#{@selected}", session: %{"id" => @selected, "mount" => @selected, "nested" => true}) %>
        <% end %>
      </section>
    </main>
    """
  end
end
