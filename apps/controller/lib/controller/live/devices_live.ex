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
    {:ok, socket |> assign(night: Settings.get("night", false), notice: nil, subscribed: MapSet.new()) |> refresh()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}
  def handle_info({:mount, _snap}, socket), do: {:noreply, refresh(socket)}

  @impl true
  def handle_event("scan", _, socket) do
    Mount.scan()
    {:noreply, socket |> assign(notice: "scanned") |> refresh()}
  end

  def handle_event("connect", %{"port" => port}, socket) do
    Mount.connect_port(port)
    {:noreply, socket |> assign(notice: "starting a driver on #{Path.basename(port)}…") |> refresh()}
  end

  def handle_event("disconnect", %{"port" => port}, socket) do
    Mount.disconnect_port(port)
    {:noreply, socket |> assign(notice: "disconnected #{Path.basename(port)}") |> refresh()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

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
      any_real: Enum.any?(mounts, &(&1.id != "sim" and &1.connected)),
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
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card class={if @any_real, do: "state ok", else: "state"}>
        <div class="state-line">
          <strong>{if @any_real, do: "Telescope connected", else: "No telescope connected"}</strong>
          <span :if={!@any_real} class="dim">looking for a cable every few seconds</span>
        </div>
      </.card>

      <.card :for={m <- @mounts} title={m.id}>
        <:aside>
          <.badge on={m.connected}>{if m.connected, do: "answering", else: "not answering"}</.badge>
          <.badge :if={m.id == "sim"}>simulator</.badge>
          <.badge :if={m.node != :nonode@nohost} dim>{m.node}</.badge>
        </:aside>
        <.kv :if={m.connected} label="state" value={"#{if m.homed, do: "homed", else: "not homed"} · tracking #{m.tracking} · firmware #{m.firmware}"} />
        <.kv :if={!m.connected && m[:error]} label="problem"><span class="err">{describe_error(m.error)}</span></.kv>
        <.row>
          <.btn navigate={~p"/bench?#{[mount: m.id]}"}>Drive it ›</.btn>
          <.btn navigate={~p"/setup/#{m.id}"}>Setup ›</.btn>
          <.btn :if={m.id in Enum.map(@status.manual, &Path.basename/1)} phx-click="disconnect" phx-value-port={port_of(m.id, @status.manual)}>Disconnect</.btn>
        </.row>
      </.card>
      <.hint :if={@mounts == []}>No drivers running.</.hint>

      <% likely = Enum.filter(@ports, &(&1.looks_like_mount or &1.mount_id)) %>
      <.card title="Telescope Cable">
        <div :for={p <- likely} class="port">
          <div class="line">
            <strong>{Path.basename(p.path)}</strong>
            <.badge :if={p.looks_like_mount} on>EQDIR cable</.badge>
            <.badge :if={p.mount_id}>driver on</.badge>
          </div>
          <.row :if={!p.mount_id or p.path in @status.manual}>
            <.btn :if={!p.mount_id} phx-click="connect" phx-value-port={p.path}>Connect</.btn>
            <.btn :if={p.mount_id && p.path in @status.manual} phx-click="disconnect" phx-value-port={p.path}>Disconnect</.btn>
          </.row>
        </div>
        <.hint :if={likely == []}>No EQDIR cable seen on this machine. Plug it into this machine's USB, then Scan.</.hint>
        <.row>
          <.btn navigate={~p"/devices/ports"} class="btn-ghost">All serial ports · {length(@ports)} ›</.btn>
        </.row>
      </.card>

      <.card title="Reach This Machine">
        <.kv label="Wi-Fi"><span :for={h <- @host} class="mono">http://{h}:4000 </span></.kv>
        <.kv :if={@tunnel} label="anywhere"><a class="mono" href={@tunnel}>{@tunnel}</a></.kv>
        <.kv :if={node() != :nonode@nohost} label="node" value={to_string(node())} />
      </.card>

      <.hint>Won't connect? <.link href={~p"/docs/devices"}>The checklist ›</.link></.hint>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end

  defp describe_error({"e", :ra, :timeout}), do: "port opened but the mount didn't answer — power? wrong jack? another program on the port?"
  defp describe_error({_, _, :timeout}), do: "the mount stopped answering"
  defp describe_error(:eacces), do: "permission denied opening the port"
  defp describe_error(:enoent), do: "the port vanished (cable unplugged?)"
  defp describe_error(:eagain), do: "the port is busy — another program has it open"
  defp describe_error(e), do: inspect(e)

  defp port_of(id, manual), do: Enum.find(manual, &(Path.basename(&1) == id)) || id

end
