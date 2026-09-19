defmodule Controller.DevicesLive do
  @moduledoc """
  Everything about getting connected: which serial ports this machine sees,
  which of them has a driver, whether the mount is answering, the actual error
  when it isn't, and the buttons to scan, connect a port by hand, or disconnect.
  """
  use Controller, :live_view

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
        if MapSet.member?(acc, m.id), do: acc, else: (Mount.subscribe(m.id); MapSet.put(acc, m.id))
      end)

    ports = Mount.ports()
    status = Mount.discovery_status()

    assign(socket,
      mounts: mounts,
      ports: ports,
      status: status,
      subscribed: subscribed,
      any_real: Enum.any?(mounts, &(&1.id != "sim" and &1.connected)),
      host: host_addresses()
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

  @impl true
  def render(assigns) do
    ~H"""
    <main class={["devices", @night && "night"]}>
      <header>
        <.link navigate={~p"/"} class="ghost">‹ keypad</.link>
        <span class="hdr-actions">
          <button phx-click="scan">Scan now</button>
          <.link href={~p"/docs/devices"} class="ghost help">?</.link>
        </span>
      </header>

      <section class={["card", "state", @any_real && "ok"]}>
        <strong :if={@any_real}>Telescope connected</strong>
        <strong :if={!@any_real}>No telescope connected</strong>
        <span class="dim">
          last scan {if @status.last_scan, do: Calendar.strftime(@status.last_scan, "%H:%M:%S UTC"), else: "—"} · rescans every 3 s
        </span>
      </section>

      <h2>Mounts</h2>
      <section :for={m <- @mounts} class="card mount">
        <div class="line">
          <strong>{m.id}</strong>
          <span class={["badge", m.connected && "on"]}>{if m.connected, do: "answering", else: "not answering"}</span>
          <span :if={m.id == "sim"} class="badge">simulator</span>
          <span :if={m.node != :nonode@nohost} class="badge dim">{m.node}</span>
        </div>
        <div :if={m.connected} class="dim">firmware {m.firmware} · {if m.homed, do: "homed", else: "not homed"} · tracking {m.tracking}</div>
        <div :if={!m.connected && m[:error]} class="err">{describe_error(m.error)}</div>
        <div class="line">
          <.link navigate={~p"/#{m.id}"} class="btn-link">Keypad</.link>
          <.link navigate={~p"/sky/#{m.id}"} class="btn-link">Sky</.link>
          <button :if={m.id in Enum.map(@status.manual, &Path.basename/1)} phx-click="disconnect" phx-value-port={port_of(m.id, @status.manual)}>Disconnect</button>
        </div>
      </section>
      <p :if={@mounts == []} class="dim">No drivers running.</p>

      <h2>Serial ports on this machine</h2>
      <section :for={p <- @ports} class="card port">
        <div class="line">
          <strong>{Path.basename(p.path)}</strong>
          <span :if={p.looks_like_mount} class="badge on">FTDI · looks like an EQDIR cable</span>
          <span :if={p.mount_id} class="badge">driver: {p.mount_id}</span>
        </div>
        <div class="dim">
          {p.manufacturer || "unknown maker"}<span :if={p.description}> · {p.description}</span>
          <span :if={p.vendor_id}> · {hex(p.vendor_id)}:{hex(p.product_id)}</span>
          <span :if={p.serial_number}> · s/n {p.serial_number}</span>
        </div>
        <div class="line">
          <button :if={!p.mount_id} phx-click="connect" phx-value-port={p.path}>Connect</button>
          <button :if={p.mount_id && p.path in @status.manual} phx-click="disconnect" phx-value-port={p.path}>Disconnect</button>
        </div>
      </section>
      <p :if={@ports == []} class="dim">The OS lists no serial ports. The cable isn't plugged into this machine, or the hub isn't passing it through.</p>

      <h2>This machine</h2>
      <section class="card">
        <div class="dim">Phone on the same Wi-Fi: <span :for={h <- @host} class="mono">http://{h}:4000 </span></div>
        <div class="dim">Node: {node()}</div>
      </section>

      <h2>If it won't connect</h2>
      <section class="card checklist">
        <ol>
          <li>Mount power LED steady? (12 V, centre-positive, switch on.)</li>
          <li>Cable in the mount's <strong>HAND CONTROL</strong> jack (RJ45), not AUTO GUIDE (RJ12)?</li>
          <li>Does a port appear above when you plug the USB in? If not: other USB port, no hub, another cable.</li>
          <li>Port appears but "not answering": power-cycle the mount, then Scan.</li>
          <li>Another program holding the port (a probe script, a terminal)? Quit it.</li>
        </ol>
        <.link href={~p"/docs/devices"} class="help">more ›</.link>
      </section>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </main>
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
