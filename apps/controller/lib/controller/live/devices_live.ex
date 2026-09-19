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
        <.back navigate={~p"/"} label="bench" />
        <.title>devices</.title>
        <.actions><.btn phx-click="scan">Scan now</.btn><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card class={if @any_real, do: "state ok", else: "state"}>
        <div class="state-line">
          <strong>{if @any_real, do: "Telescope connected", else: "No telescope connected"}</strong>
          <span class="dim">last scan {if @status.last_scan, do: Calendar.strftime(@status.last_scan, "%H:%M:%S UTC"), else: "—"} · every 3 s</span>
        </div>
      </.card>

      <.card :for={m <- @mounts} title={m.id}>
        <:aside>
          <.badge on={m.connected}>{if m.connected, do: "answering", else: "not answering"}</.badge>
          <.badge :if={m.id == "sim"}>simulator</.badge>
          <.badge :if={m.node != :nonode@nohost} dim>{m.node}</.badge>
        </:aside>
        <.kv :if={m.connected} label="firmware" value={m.firmware} />
        <.kv :if={m.connected} label="state" value={"#{if m.homed, do: "homed", else: "not homed"} · tracking #{m.tracking}"} />
        <.kv :if={!m.connected && m[:error]} label="problem"><span class="err">{describe_error(m.error)}</span></.kv>
        <.row>
          <.btn navigate={~p"/#{m.id}"}>Keypad</.btn>
          <.btn navigate={~p"/sky/#{m.id}"}>Sky</.btn>
          <.btn navigate={~p"/setup/#{m.id}"}>Setup</.btn>
          <.btn :if={m.id in Enum.map(@status.manual, &Path.basename/1)} phx-click="disconnect" phx-value-port={port_of(m.id, @status.manual)}>Disconnect</.btn>
        </.row>
      </.card>
      <.hint :if={@mounts == []}>No drivers running.</.hint>

      <.card title="Serial ports on this machine">
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
      </.card>

      <.card title="Reach this machine">
        <.kv label="Wi-Fi"><span :for={h <- @host} class="mono">http://{h}:4000 </span></.kv>
        <.kv :if={@tunnel} label="anywhere"><a class="mono" href={@tunnel}>{@tunnel}</a></.kv>
        <.kv label="node" value={to_string(node())} />
      </.card>

      <.card title="If it won't connect">
        <ol class="checklist">
          <li>Mount power LED steady? 12 V, centre-positive, switch on.</li>
          <li>Cable in the mount's <strong>HAND CONTROL</strong> jack (RJ45), not AUTO GUIDE (RJ12).</li>
          <li>No port above when you plug in? Other USB port, no hub, another cable.</li>
          <li>Port but "not answering": power-cycle the mount, then Scan.</li>
          <li>Another program holding the port? Quit it.</li>
        </ol>
        <.hint><.link href={~p"/docs/devices"} class="help">more ›</.link></.hint>
      </.card>

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

  defp hex(nil), do: "—"
  defp hex(n), do: n |> Integer.to_string(16) |> String.downcase() |> String.pad_leading(4, "0")
end
