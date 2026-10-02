defmodule Controller.DevicesLive do
  @moduledoc """
  Everything about getting connected: which serial ports this machine sees,
  which of them has a driver, whether the mount is answering, the actual error
  when it isn't, and the buttons to scan, connect a port by hand, or disconnect.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @tick_ms 3_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@tick_ms, :tick)
    # boxes on the network, when this machine is a node of the cluster
    cluster = Process.whereis(Telescope.Boxes) != nil
    if connected?(socket) and cluster, do: Telescope.Boxes.subscribe()

    {:ok,
     socket
     |> assign(page_title: "Devices", night: Settings.get("night", false), notice: nil, subscribed: MapSet.new())
     |> assign(cluster: cluster, boxes: if(cluster, do: Telescope.Boxes.list(), else: []))
     |> refresh()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}
  def handle_info({:mount, _snap}, socket), do: {:noreply, refresh(socket)}
  # a box joined or left: its mounts come and go with it
  def handle_info({:boxes, boxes}, socket), do: {:noreply, socket |> assign(boxes: boxes) |> refresh()}

  @impl true
  def handle_event("scan", _, socket) do
    Mount.scan()
    {:noreply, socket |> assign(notice: "Scanned") |> refresh()}
  end

  def handle_event("connect", %{"port" => port}, socket) do
    Mount.connect_port(port)
    {:noreply, socket |> assign(notice: "Starting a driver on #{Path.basename(port)}…") |> refresh()}
  end

  def handle_event("disconnect", %{"port" => port}, socket) do
    Mount.disconnect_port(port)
    {:noreply, socket |> assign(notice: "Disconnected #{Path.basename(port)}") |> refresh()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  def handle_event("box_connect", %{"node" => node}, socket) do
    node = String.trim(node)

    notice =
      cond do
        not String.contains?(node, "@") -> "A node name is name@host, e.g. telescope@observatory.local"
        Telescope.Boxes.connect(node) == :ok -> "Connected #{node}"
        true -> "No answer from #{node}: the name must match the box's exactly, and the cookie too"
      end

    {:noreply, socket |> assign(notice: notice, boxes: Telescope.Boxes.list()) |> refresh()}
  end

  def handle_event("box_forget", %{"node" => node}, socket) do
    Telescope.Boxes.forget(node)
    {:noreply, socket |> assign(notice: "Disconnected #{node}", boxes: Telescope.Boxes.list()) |> refresh()}
  end

  defp refresh(socket) do
    mounts =
      for ref <- Mount.list() do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> %{id: ref.id, node: ref.node, connected: false, error: :unreachable, axes: %{}, firmware: nil, tracking: :off, homed: false}
        end
      end

    subscribed =
      Enum.reduce(mounts, socket.assigns.subscribed, fn m, acc ->
        if MapSet.member?(acc, m.id) do
          acc
        else
          Mount.subscribe(m.id)
          MapSet.put(acc, m.id)
        end
      end)

    assign(socket,
      mounts: mounts,
      ports: Mount.ports(),
      status: Mount.discovery_status(),
      subscribed: subscribed,
      any_real: Enum.any?(mounts, &(not Mount.simulated?(&1.id) and &1.connected)),
      host: host_addresses(),
      tunnel: tunnel_url()
    )
  end

  defp host_addresses do
    case :inet.getifaddrs() do
      {:ok, ifs} ->
        for {_name, opts} <- ifs,
            {:addr, {a, b, c, d}} <- opts,
            a != 127,
            not (a == 169 and b == 254),
            do: "#{a}.#{b}.#{c}.#{d}"

      _ ->
        []
    end
  end

  # ~/.observatory/tunnel.sh keeps a Cloudflare quick tunnel up and writes its URL here.
  defp tunnel_url do
    case File.read(Path.join([System.user_home!(), ".observatory", "tunnel_url"])) do
      {:ok, "https://" <> _ = u} -> String.trim(u)
      _ -> nil
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="devices" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" />
        <.title>Devices</.title>
        <.actions><.help href={~p"/docs/devices"} label="devices" /></.actions>
      </:header>

      <.card class={if @any_real, do: "state ok", else: "state"}>
        <div class="state-line" role="status" aria-live="polite">
          <strong>{if @any_real, do: "Telescope connected", else: "No telescope connected"}</strong>
          <span :if={!@any_real} class="dim">Looking for a cable every few seconds</span>
        </div>
      </.card>

      <.card :for={m <- @mounts} title={m.id}>
        <:aside>
          <.badge on={m.connected}>{if m.connected, do: "answering", else: "not answering"}</.badge>
          <.badge :if={Mount.simulated?(m.id)}>Simulator</.badge>

        </:aside>
        <.kv :if={m.node != :nonode@nohost} label="node"><span class="mono">{m.node}</span></.kv>
        <.kv :if={m.connected} label="state" value={"#{if m.homed, do: "zeroed", else: "axes not zeroed"} · tracking #{m.tracking} · firmware #{m.firmware}"} />
        <.kv :if={!m.connected && m[:error]} label="problem"><span class="err">{describe_error(m.error)}</span></.kv>
        <.row>
          <.btn navigate={~p"/bench?#{[mount: m.id]}"}>Drive It ›</.btn>
          <.btn navigate={~p"/setup/#{m.id}"}>Setup ›</.btn>
          <.btn :if={m.id in Enum.map(@status.manual, &Path.basename/1)} phx-click="disconnect" phx-value-port={port_of(m.id, @status.manual)} aria-label={"Disconnect #{m.id}"}>Disconnect</.btn>
        </.row>
      </.card>
      <.hint :if={@mounts == []}>No drivers running.</.hint>

      <.card :if={@cluster} title="Boxes">
        <.items :if={@boxes != []} label="boxes on this network">
          <.item :for={b <- @boxes} as="li" label={b.name} detail={box_detail(b)}>
            <.btn :if={b.node && !b.connected} phx-click="box_connect" phx-value-node={b.node} aria-label={"Connect #{b.name}"}>Connect</.btn>
            <.btn :if={b.connected} phx-click="box_forget" phx-value-node={b.node} aria-label={"Disconnect #{b.name}"}>Disconnect</.btn>
          </.item>
        </.items>
        <.hint :if={@boxes == []}>None heard yet. A box on this network answers within about 10 s.</.hint>
        <form phx-submit="box_connect" class="box-connect" aria-label="connect a box by node name">
          <label>
            Node
            <input name="node" type="text" class="field" placeholder="telescope@observatory.local" autocomplete="off" autocapitalize="off" spellcheck="false" />
          </label>
          <.btn type="submit">Connect</.btn>
        </form>
        <.hint>For a box that does not say its node name. Connected boxes are reconnected after a reboot.</.hint>
      </.card>

      <% likely = Enum.filter(@ports, &(&1.looks_like_mount or &1.mount_id)) %>
      <.card title="Telescope Cable">
        <ul :if={likely != []} class="ports" role="list" aria-label="likely telescope cables">
          <li :for={p <- likely} class="port">
            <div class="line">
              <strong>{Path.basename(p.path)}</strong>
              <.badge :if={p.looks_like_mount} on>EQDIR cable</.badge>
              <.badge :if={p.mount_id}>driver on</.badge>
            </div>
            <.row :if={!p.mount_id or p.path in @status.manual}>
              <.btn :if={!p.mount_id} phx-click="connect" phx-value-port={p.path} aria-label={"Connect #{Path.basename(p.path)}"}>Connect</.btn>
              <.btn :if={p.mount_id && p.path in @status.manual} phx-click="disconnect" phx-value-port={p.path} aria-label={"Disconnect #{Path.basename(p.path)}"}>Disconnect</.btn>
            </.row>
          </li>
        </ul>
        <.hint :if={likely == []}>No EQDIR cable seen on this machine. Plug it into this machine's USB, then Scan.</.hint>
        <.row>
          <.btn navigate={~p"/devices/ports"} class="btn-ghost">All Serial Ports · {length(@ports)} ›</.btn>
        </.row>
      </.card>

      <.card title="Reach This Machine">
        <.kv label="Wi-Fi"><span :for={h <- @host} class="mono">http://{h}:4000 </span></.kv>
        <.kv :if={@tunnel} label="anywhere"><a class="mono" href={@tunnel}>{@tunnel}</a></.kv>
        <.kv :if={node() != :nonode@nohost} label="node" value={to_string(node())} />
      </.card>

      <.hint>Won't connect? <.link href={~p"/docs/devices"}>The Checklist ›</.link></.hint>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp describe_error({"e", :ra, :timeout}), do: "Port opened but the mount didn't answer: power? wrong jack? another program on the port?"
  defp describe_error({_, _, :timeout}), do: "The mount stopped answering"
  defp describe_error(:eacces), do: "Permission denied opening the port"
  defp describe_error(:enoent), do: "The port vanished (cable unplugged?)"
  defp describe_error(:eagain), do: "The port is busy: another program has it open"
  defp describe_error(e), do: inspect(e)

  defp box_detail(%{connected: true} = b), do: "#{b.ip || "remembered"} · connected as #{b.node}"
  defp box_detail(%{node: nil} = b), do: "#{b.ip} · does not say its node name; type it below"
  defp box_detail(%{ip: nil} = b), do: "remembered · not reachable, retrying #{b.node}"
  defp box_detail(b), do: "#{b.ip} · #{b.node}"

  defp port_of(id, manual), do: Enum.find(manual, &(Path.basename(&1) == id)) || id

end
