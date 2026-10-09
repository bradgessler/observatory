defmodule Controller.DevicesLive do
  @moduledoc """
  Every piece of hardware, as a list: the mounts, the cameras, the game
  controllers, the boxes on the network, and this machine. Each row is a
  name over where it is, with its state on the right; a row opens that
  device's own page, where the few things done to the device itself live
  (connect, disconnect, use it). Nothing here drives the telescope: that's
  Controls. Setting it up is Alignment.

  Everything is found by itself when plugged in, so this is where you look
  to see what was, and, when there's none, how to add one.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Settings, Words}

  @tick_ms 3_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@tick_ms, :tick)
    # boxes on the network, when this machine is a node of the cluster
    cluster = Process.whereis(Telescope.Boxes) != nil
    if connected?(socket) and cluster, do: Telescope.Boxes.subscribe()
    if connected?(socket), do: Controller.Power.subscribe()
    if connected?(socket), do: Settings.subscribe()

    {:ok,
     socket
     |> assign(page_title: "Devices", night: Settings.get("night", false), notice: nil, subscribed: MapSet.new())
     |> assign(cluster: cluster, boxes: if(cluster, do: Telescope.Boxes.list(), else: []))
     |> refresh()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}
  def handle_info({:mount, _snap}, socket), do: {:noreply, refresh(socket)}
  def handle_info({:power, _}, socket), do: {:noreply, refresh(socket)}
  # a box joined or left: its mounts come and go with it
  def handle_info({:boxes, boxes}, socket), do: {:noreply, socket |> assign(boxes: boxes) |> refresh()}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("scan", _, socket) do
    Mount.scan()
    {:noreply, socket |> assign(notice: "Scanned") |> refresh()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  # what the telescope camera is doing, in a word
  defp cam_state(%{camera: nil}), do: "None"
  defp cam_state(%{video: true}), do: "Video"
  defp cam_state(%{live: true}), do: "Live View"
  defp cam_state(%{error: e}) when is_binary(e), do: "Problem"
  defp cam_state(_), do: "Idle"

  defp cam_detail(%{camera: nil}), do: "None: plug a USB camera into the focuser"
  defp cam_detail(%{sim: true} = cam), do: "Simulator on #{Words.host(cam[:node] || node())}"
  defp cam_detail(cam), do: "#{cam.camera} · #{Words.host(cam[:node] || node())}"

  defp watch_state(%{tool: nil}), do: "None"
  defp watch_state(%{streaming: true}), do: "Video"
  defp watch_state(%{last_error: e}) when is_binary(e), do: "Problem"
  defp watch_state(%{enabled: true}), do: "Stills"
  defp watch_state(_), do: "Idle"

  defp watch_detail(%{tool: nil}), do: "None: needs imagesnap on a Mac or fswebcam on Linux"
  defp watch_detail(w), do: "#{w[:device] || "Default camera"} · #{Words.host(node())}"

  # a camera this machine sees that isn't the telescope camera
  defp spare?(c, %{camera: name, node: n}) when is_binary(name) and n == node(), do: not String.starts_with?(name, c.name)
  defp spare?(_, _), do: true

  defp pad_name(p) do
    dev = p[:device] || %{}
    (is_map(dev) && (dev[:product] || dev[:name])) || p[:parser] || "Game controller"
  end

  defp mount_detail(m, telescope) do
    kind = if Mount.simulated?(m.id), do: "Simulator", else: "EQDIR cable"
    where = Words.host(m.node)
    selected = if telescope && telescope.id == m.id, do: " · selected", else: ""
    "#{kind} on #{where}#{selected}"
  end

  defp box_detail(%{connected: true} = b), do: "#{b.ip || "Remembered"} · #{b.node}"
  defp box_detail(%{node: nil} = b), do: "#{b.ip} · doesn't say its node name"
  defp box_detail(%{ip: nil} = b), do: "Not reachable · #{b.node}"
  defp box_detail(b), do: "#{b.ip} · #{b.node}"

  defp safe_call(fun, default) do
    fun.()
  catch
    _, _ -> default
  end

  defp refresh(socket) do
    mounts =
      for ref <- Mount.list() do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> %{id: ref.id, node: ref.node, connected: false, error: :unreachable}
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

    ports = Mount.ports()

    assign(socket,
      mounts: Enum.sort_by(mounts, &{Mount.simulated?(&1.id), &1.id}),
      ports: ports,
      # an EQDIR cable with no driver on it yet: Connect is on Serial Ports
      loose: Enum.filter(ports, &(&1.looks_like_mount and is_nil(&1.mount_id))),
      subscribed: subscribed,
      any_real: Enum.any?(mounts, &(not Mount.simulated?(&1.id) and &1.connected)),
      cam: Map.put_new(safe_call(fn -> Controller.ScopeCamera.find() end, nil) || %{}, :camera, nil),
      watch: Map.put_new(safe_call(fn -> Watch.status() end, nil) || %{}, :tool, nil),
      cameras_here: safe_call(fn -> Controller.ScopeCamera.Device.list() end, []),
      pads: safe_call(fn -> Input.devices() |> Enum.reject(&is_nil/1) end, []),
      power: Controller.Power.status(),
      host: host_addresses(),
      port: port_suffix(),
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

  # the port this server answers on, as a URL says it: none for 80 (the box), ":4000" for the Mac's dev server
  defp port_suffix do
    case Controller.Endpoint.config(:http)[:port] do
      p when p in [nil, 80] -> ""
      p -> ":#{p}"
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
        <.back navigate={~p"/"} label="Home" section="System" />
        <.title>Devices</.title>
        <.actions><.help href={~p"/docs/devices"} label="devices" /><.stop /></.actions>
      </:header>

      <.card class={if @any_real, do: "state ok", else: "state"}>
        <div class="state-line" role="status" aria-live="polite">
          <strong>{if @any_real, do: "Telescope connected", else: "No telescope connected"}</strong>
          <span :if={!@any_real} class="dim">Looking for a cable every few seconds</span>
        </div>
      </.card>

      <.card title="Mounts">
        <.items label="mounts">
          <.link_item :for={m <- @mounts} navigate={~p"/devices/mount/#{m.id}"} label={m.id} detail={mount_detail(m, @telescope)}>
            <:aside><.badge on={m.connected} warn={!m.connected}>{if m.connected, do: "Answering", else: "Not answering"}</.badge></:aside>
          </.link_item>
          <.link_item :for={p <- @loose} navigate={~p"/devices/ports"} label={Path.basename(p.path)} detail="EQDIR cable · no driver yet">
            <:aside><.badge>Connect</.badge></:aside>
          </.link_item>
          <.link_item navigate={~p"/devices/ports"} label="Serial Ports" detail="Every port this machine sees">
            <:aside>{length(@ports)}</:aside>
          </.link_item>
        </.items>
        <.hint :if={@mounts == []}>None yet. Plug the EQDIR cable into this machine or a box; it is found within a few seconds.</.hint>
        <.row><.btn variant="ghost" phx-click="scan">Scan Now</.btn></.row>
      </.card>

      <%!-- the cameras by what each is for; a camera's page is where it's used and set --%>
      <.card title="Cameras">
        <.items label="cameras">
          <.link_item navigate={~p"/cameras/telescope"} label="Telescope Camera" detail={cam_detail(@cam)}>
            <:aside><.badge on={@cam[:camera] != nil and cam_state(@cam) != "Problem"} warn={cam_state(@cam) == "Problem"}>{cam_state(@cam)}</.badge></:aside>
          </.link_item>
          <.link_item navigate={~p"/cameras/observatory"} label="Observatory Camera" detail={watch_detail(@watch)}>
            <:aside><.badge on={watch_state(@watch) in ["Stills", "Video"]} warn={watch_state(@watch) == "Problem"}>{watch_state(@watch)}</.badge></:aside>
          </.link_item>
          <.item :for={c <- Enum.filter(@cameras_here, &spare?(&1, @cam))} as="li" label={c.name} detail={"#{c.path} · not used"} />
        </.items>
        <.hint>A camera is found within a few seconds of being plugged in; the first that gives pictures becomes the telescope camera. <.link href={~p"/docs/cameras"}>About the cameras</.link></.hint>
      </.card>

      <.card title="Game Controllers">
        <.items :if={@pads != []} label="game controllers">
          <.link_item :for={p <- @pads} navigate={~p"/input"} label={pad_name(p)} detail={"On #{Words.host(p[:node] || node())}"} />
        </.items>
        <.hint :if={@pads == []}>None. Plug a USB game controller into this machine or a box; it shows up here by itself. <.link href={~p"/docs/game-controller"}>Which ones work</.link></.hint>
      </.card>

      <.card :if={@cluster} title="Boxes">
        <.items label="boxes on this network">
          <.link_item :for={b <- @boxes} navigate={~p"/devices/boxes"} label={b.name} detail={box_detail(b)}>
            <:aside><.badge on={b.connected}>{if b.connected, do: "Connected", else: "Not connected"}</.badge></:aside>
          </.link_item>
          <.link_item navigate={~p"/devices/boxes"} label="Add a Box" detail="By its node name, for one that doesn't announce itself" />
        </.items>
      </.card>

      <.card title="This Machine">
        <.kv label="Hostname"><span class="mono">{Words.host(node())}</span></.kv>
        <.kv label="Address"><span :for={h <- @host} class="mono">http://{h}{@port} </span></.kv>
        <.kv :if={@tunnel} label="Anywhere"><a class="mono" href={@tunnel}>{@tunnel}</a></.kv>
        <.kv :if={node() != :nonode@nohost} label="Node" value={to_string(node())} />
        <.kv :if={@power.monitored} label="Power">
          <span class={@power.dips > 0 && "tone-caution"}>
            {if @power.low, do: "Low right now", else: "Holding"}{if @power.dips > 0, do: ": dipped #{@power.dips} #{if @power.dips == 1, do: "time", else: "times"} since the box started", else: ": no dips since the box started"}
          </span>
        </.kv>
        <.hint :if={@power.monitored && Controller.Power.words(@power)}>{Controller.Power.words(@power)}</.hint>
      </.card>

      <.hint>Won't connect? <.link href={~p"/docs/devices"}>The Checklist ›</.link></.hint>

      <.notice notice={@notice} />
    </.page>
    """
  end
end
