defmodule Controller.BoxesLive do
  @moduledoc """
  The boxes on this network (`/devices/boxes`): each Raspberry Pi running
  the observatory, whether this machine is connected to it, and connecting
  one by its node name when it doesn't announce itself. A connected box's
  mounts, cameras and game controllers show on Devices like this machine's.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(_params, _session, socket) do
    cluster = Process.whereis(Telescope.Boxes) != nil

    if connected?(socket) do
      Settings.subscribe()
      if cluster, do: Telescope.Boxes.subscribe()
    end

    {:ok,
     assign(socket,
       page_title: "Boxes",
       night: Settings.get("night", false),
       notice: nil,
       cluster: cluster,
       boxes: if(cluster, do: Telescope.Boxes.list(), else: [])
     )}
  end

  @impl true
  def handle_info({:boxes, boxes}, socket), do: {:noreply, assign(socket, boxes: boxes)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("connect", %{"node" => node}, socket) do
    node = String.trim(node)

    notice =
      cond do
        not String.contains?(node, "@") -> "A node name is name@host, e.g. telescope@observatory.local"
        Telescope.Boxes.connect(node) == :ok -> "Connected #{node}"
        true -> "No answer from #{node}: the name must match the box's exactly, and the cookie too"
      end

    {:noreply, assign(socket, notice: notice, boxes: Telescope.Boxes.list())}
  end

  def handle_event("forget", %{"node" => node}, socket) do
    Telescope.Boxes.forget(node)
    {:noreply, assign(socket, notice: "Disconnected #{node}", boxes: Telescope.Boxes.list())}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp detail(%{connected: true} = b), do: "#{b.ip || "Remembered"} · connected as #{b.node}"
  defp detail(%{node: nil} = b), do: "#{b.ip} · doesn't say its node name; type it below"
  defp detail(%{ip: nil} = b), do: "Remembered · not reachable, retrying #{b.node}"
  defp detail(b), do: "#{b.ip} · #{b.node}"

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="boxes" night={@night}>
      <:header>
        <.back navigate={~p"/devices"} label="Devices" />
        <.title>Boxes</.title>
        <.actions><.help href={~p"/docs/devices"} label="devices" /><.stop /></.actions>
      </:header>

      <.card :if={!@cluster}>
        <p class="find-line" role="status">This machine isn't part of a cluster, so it doesn't look for boxes.</p>
      </.card>

      <.card :if={@cluster} title="On This Network">
        <.items :if={@boxes != []} label="boxes on this network">
          <.item :for={b <- @boxes} as="li" label={b.name} detail={detail(b)}>
            <.btn :if={b.node && !b.connected} phx-click="connect" phx-value-node={b.node} aria-label={"Connect #{b.name}"}>Connect</.btn>
            <.btn :if={b.connected} phx-click="forget" phx-value-node={b.node} aria-label={"Disconnect #{b.name}"}>Disconnect</.btn>
          </.item>
        </.items>
        <.hint :if={@boxes == []}>None heard yet. A box on this network answers within about 10 s.</.hint>
      </.card>

      <.card :if={@cluster} title="Connect by Node Name">
        <form phx-submit="connect" class="box-connect" aria-label="connect a box by node name">
          <label>
            Node
            <input name="node" type="text" class="field" placeholder="telescope@observatory.local" autocomplete="off" autocapitalize="off" spellcheck="false" />
          </label>
          <.btn type="submit">Connect</.btn>
        </form>
        <.hint>For a box that doesn't say its node name. A connected box is reconnected after a reboot.</.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
