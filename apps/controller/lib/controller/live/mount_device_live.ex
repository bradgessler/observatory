defmodule Controller.MountDeviceLive do
  @moduledoc """
  One mount, as a device (`/devices/mount/:id`): where it is, whether it
  answers and, when it doesn't, what to check; its port, firmware and state.
  And the few things done to the device itself: use it on every page,
  disconnect a port that was connected by hand, go to its setup. Driving it
  is on the Controls pages.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Settings, Words}

  @tick_ms 3_000

  @impl true
  def mount(%{"id" => id}, _session, socket) do
    if connected?(socket) do
      :timer.send_interval(@tick_ms, :tick)
      Settings.subscribe()
      Mount.subscribe(id)
    end

    {:ok,
     socket
     |> assign(id: id, page_title: Words.title(id, "Mount"), night: Settings.get("night", false), notice: nil)
     |> refresh()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}
  def handle_info({:mount, %{id: id} = snap}, %{assigns: %{id: id}} = socket), do: {:noreply, assign(socket, snap: snap)}
  def handle_info({:mount, _}, socket), do: {:noreply, socket}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("disconnect", _, socket) do
    if port = socket.assigns.manual, do: on(socket.assigns.node, :disconnect_port, [port], :ok)
    {:noreply, socket |> assign(notice: "Disconnected #{socket.assigns.id}") |> refresh()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp refresh(socket) do
    id = socket.assigns.id
    ref = Enum.find(Mount.list(), &(&1.id == id))

    snap =
      if ref do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> %{id: id, node: ref.node, connected: false, error: :unreachable}
        end
      end

    # the port and how it was connected are known on the machine the cable is in
    node = if ref, do: ref.node, else: node()
    status = on(node, :discovery_status, [], %{manual: []})

    assign(socket,
      ref: ref,
      snap: snap,
      node: node,
      port: Enum.find(on(node, :ports, [], []), &(&1.mount_id == id)),
      # connected by hand on Serial Ports (not found by the scan): disconnecting is ours to offer
      manual: Enum.find(status.manual, &(Path.basename(&1) == id))
    )
  end

  defp on(node, fun, args, default) when node == node(), do: apply(Mount, fun, args) || default

  defp on(node, fun, args, default) do
    :erpc.call(node, Mount, fun, args, 2_000)
  catch
    _, _ -> default
  end

  defp tracking_words(nil), do: Words.none()
  defp tracking_words(:off), do: "Off"
  defp tracking_words(t), do: t |> to_string() |> String.replace("_", " ") |> String.capitalize()

  @impl true
  def render(assigns) do
    assigns = assign(assigns, selected: assigns.telescope && assigns.telescope.id == assigns.id)

    ~H"""
    <.page id="mount-device" night={@night}>
      <:header>
        <.back navigate={~p"/devices"} label="Devices" />
        <.title>{@id}</.title>
        <.actions><.help href={~p"/docs/devices"} label="devices" /><.stop /></.actions>
      </:header>

      <%= if @snap do %>
        <.card title="Status">
          <:aside>
            <.badge on={@snap.connected} warn={!@snap.connected}>{if @snap.connected, do: "Answering", else: "Not answering"}</.badge>
          </:aside>
          <.kv label="Kind" value={if Mount.simulated?(@id), do: "Simulator: no telescope on the cable", else: "Sky-Watcher mount on an EQDIR cable"} />
          <.kv label="Hostname"><span class="mono">{Words.host(@snap.node)}</span></.kv>
          <.kv :if={@port} label="Port"><span class="mono">{@port.path}</span></.kv>
          <.kv :if={@port && @port.manufacturer} label="Cable" value={Enum.join(Enum.reject([@port.manufacturer, @port.description], &is_nil/1), " · ")} />
          <.kv :if={@snap.connected} label="Firmware" value={@snap[:firmware] || Words.none()} />
          <.kv :if={@snap.connected} label="Home" value={if @snap[:homed], do: "Set", else: "Not set: Setup sets it"} />
          <.kv :if={@snap.connected} label="Tracking" value={tracking_words(@snap[:tracking])} />
          <.kv :if={!@snap.connected && @snap[:error]} label="Problem"><span class="err">{Words.mount_problem(@snap.error)}</span></.kv>
        </.card>

        <.card title="Use">
          <p class="find-line" role="status">
            {if @selected, do: "Every page drives this mount for you.", else: "Your pages drive #{(@telescope && @telescope.id) || "no mount"}."}
          </p>
          <.row>
            <%!-- per viewer, like the tab they're on: the sidebar's switcher does the same --%>
            <.btn :if={!@selected} href={~p"/telescope/#{@id}?#{[return: ~p"/devices/mount/#{@id}"]}"}>Use This Mount</.btn>
            <.btn navigate={~p"/setup/#{@id}"}>Setup ›</.btn>
          </.row>
        </.card>

        <.card :if={@manual} title="Connection">
          <.hint>Connected by hand on Serial Ports. Disconnecting stops its driver; the port stays where it is.</.hint>
          <.row><.btn phx-click="disconnect" aria-label={"Disconnect #{@id}"}>Disconnect</.btn></.row>
        </.card>

        <.hint :if={!@snap.connected}>Won't connect? <.link href={~p"/docs/devices"}>The Checklist ›</.link></.hint>
      <% else %>
        <.card>
          <p class="find-line" role="status">No mount called {@id} right now.</p>
          <.hint>Its driver stopped, its cable came out, or the box it's on is off. It's found again by itself when it's back.</.hint>
          <.row><.btn navigate={~p"/devices"}>Devices ›</.btn></.row>
        </.card>
      <% end %>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
