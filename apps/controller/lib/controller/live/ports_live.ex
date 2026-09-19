defmodule Controller.PortsLive do
  @moduledoc "Every serial port the OS lists, with maker and ids, and Connect for the ones that aren't obviously a telescope. The Devices page shows only the likely ones."
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      send(self(), :refresh)
    end

    {:ok, socket |> assign(night: Settings.get("night", false), notice: nil) |> refresh()}
  end

  defp refresh(socket), do: assign(socket, ports: Mount.ports(), status: Mount.discovery_status())

  @impl true
  def handle_info(:refresh, socket) do
    Process.send_after(self(), :refresh, 3_000)
    {:noreply, refresh(socket)}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("connect", %{"port" => port}, socket) do
    Mount.connect_port(port)
    {:noreply, socket |> assign(notice: "connecting #{Path.basename(port)}") |> refresh()}
  end

  def handle_event("disconnect", %{"port" => port}, socket) do
    Mount.disconnect_port(port)
    {:noreply, refresh(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="ports" night={@night}>
      <:header>
        <.back navigate={~p"/devices"} label="devices" />
        <.title>serial ports</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card title="On this machine">
        <div :for={p <- @ports} class="port">
          <div class="line">
            <strong>{Path.basename(p.path)}</strong>
            <.badge :if={p.looks_like_mount} on>FTDI · EQDIR cable</.badge>
            <.badge :if={p.mount_id}>driver: {p.mount_id}</.badge>
          </div>
          <span class="dim">
            {p.manufacturer || "unknown maker"}<span :if={p.description}> · {p.description}</span>
            <span :if={p.vendor_id}> · {hex(p.vendor_id)}:{hex(p.product_id)}</span>
            <span :if={p.serial_number}> · s/n {p.serial_number}</span>
          </span>
          <.row :if={!p.mount_id or p.path in @status.manual}>
            <.btn :if={!p.mount_id} phx-click="connect" phx-value-port={p.path}>Connect</.btn>
            <.btn :if={p.mount_id && p.path in @status.manual} phx-click="disconnect" phx-value-port={p.path}>Disconnect</.btn>
          </.row>
        </div>
        <.hint :if={@ports == []}>The OS lists no serial ports. The cable isn't plugged into this machine, or the hub isn't passing it through.</.hint>
        <.hint>Connect tries the Sky-Watcher protocol on that port. A port that isn't a telescope just won't answer.</.hint>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end

  defp hex(nil), do: "?"
  defp hex(n), do: n |> Integer.to_string(16) |> String.downcase() |> String.pad_leading(4, "0")
end
