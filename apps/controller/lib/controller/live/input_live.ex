defmodule Controller.InputLive do
  @moduledoc """
  Hardware inputs, read by the server. This page only shows what `Input` sees
  and lets you arm the mapper; there is no browser-side device code, so it
  works the same in Safari, Firefox, a phone, anything.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      Input.subscribe()
      Settings.subscribe()
      send(self(), :rescan)
    end

    # nested views get :not_mounted_at_router instead of params
    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(page_title: "Game Controller", night: Settings.get("night", false), nested: session["nested"] == true, refs: %{}, selected: params["mount"] || session["mount"] || session["telescope"], snap: nil, notice: nil, start: nil)
     |> load()
     |> rescan()}
  end

  defp load(socket) do
    assign(socket, devices: Input.devices(), seen: Input.seen(), mapper: Input.status())
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> load()}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:input, id, info}, socket) do
    devices = Enum.reject(socket.assigns.devices, &(&1.id == id)) ++ [info]
    {:noreply, assign(socket, devices: Enum.sort_by(devices, & &1.id))}
  end

  def handle_info({:input_gone, id}, socket) do
    {:noreply, assign(socket, devices: Enum.reject(socket.assigns.devices, &(&1.id == id)))}
  end

  def handle_info({:mapper, status}, socket) do
    start =
      cond do
        status.held == [] -> nil
        socket.assigns.start -> socket.assigns.start
        socket.assigns.snap && socket.assigns.snap.axes[:ra] -> {socket.assigns.snap.axes.ra.degrees, socket.assigns.snap.axes.dec.degrees}
        true -> nil
      end

    {:noreply, assign(socket, mapper: status, start: start)}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end) |> ok_or_nil()
    assign(socket, refs: refs, selected: selected, snap: snap)
  end

  # -- events -------------------------------------------------------------------------

  @impl true
  def handle_event("arm", params, socket) do
    on? = params["on"] == "true"
    if on? and socket.assigns.selected, do: Input.target(socket.assigns.selected)
    Input.arm(on?)
    {:noreply, socket |> assign(notice: if(on?, do: "The game controller now moves #{socket.assigns.selected}", else: "Watch only")) |> load()}
  end

  def handle_event("scan", _, socket) do
    Input.scan()
    {:noreply, load(socket)}
  end

  # STOP here disarms the pad as well as stopping the mount it was driving
  def handle_event("estop", _, socket) do
    Input.arm(false)
    Controller.Sky.Tracker.stop_all()
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.emergency_stop(ref) end)
    {:noreply, socket |> assign(notice: "Stopped · the game controller is watch only") |> load()}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp safe(fun) do
    try do
      fun.()
    catch
      _, _ -> {:error, :unreachable}
    end
  end

  defp ok_or_nil({:error, _}), do: nil
  defp ok_or_nil(v), do: v

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="input" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section="Controls" />
        <.title>Game Controller</.title>
        <.actions>
          <.help href={~p"/docs/game-controller"} label="the game controller" />
          <.stop click="estop" />
        </.actions>
      </:header>

      <.card title="What It Moves">
        <:aside>
          <.badge on={@mapper.action != :idle} warn={@mapper.action == :stop}>{@mapper.action_text}</.badge>
        </:aside>
        <%!-- two explicit states, not a toggle: you always see which one you're in --%>
        <.seg label="what the game controller does">
          <:opt on={!@mapper.armed} click="arm" value={%{on: "false"}}>Watch Only</:opt>
          <:opt on={@mapper.armed} live click="arm" value={%{on: "true"}} disabled={@devices == []}>Moves the Mount</:opt>
        </.seg>
        <.hint :if={@mapper.off_reason}><strong>{@mapper.off_reason}</strong></.hint>
        <.hint :if={Map.get(@mapper, :ignoring)}><strong>It is off: tap Moves the Mount</strong></.hint>
        <.kv label="Mount" value={@mapper.target || "None"} />
        <.kv :if={@snap && @snap.axes[:ra]} label="Position" value={"RA #{fmt1(@snap.axes.ra.degrees)}° · Dec #{fmt1(@snap.axes.dec.degrees)}°"} />
        <.kv :if={@start && @snap && @snap.axes[:ra]} label="Moved" value={"ΔRA #{fmt1(@snap.axes.ra.degrees - elem(@start, 0))}° · ΔDec #{fmt1(@snap.axes.dec.degrees - elem(@start, 1))}°"} />
        <.hint>Hold the trigger (button {@mapper.map.trigger}) and tilt the ball. Button {@mapper.map.stop} is STOP. <.link href={~p"/docs/game-controller#the-trigger-is-a-dead-mans-switch"}>Why the trigger?</.link></.hint>
      </.card>

      <.card :for={d <- @devices} title={device_name(d)}>
        <:aside><.badge on>{d.reports} reports</.badge><.badge :if={d.node != :nonode@nohost} dim>{Controller.Words.host(d.node)}</.badge></:aside>
        <.hint :if={d.reports == 0}>Touch the ball, a stick or a button and it shows up here.</.hint>
        <div class="axes" role="list" aria-label="axes">
          <div :for={{v, i} <- Enum.with_index(d.state.axes)} class="axis-bar" role="listitem">
            <span class="axis-i">{axis_name(i)}</span>
            <div class="bar" aria-hidden="true"><div class="fill" style={bar_style(v)}></div></div>
            <span class="axis-v">{fmt2(v)}</span>
          </div>
        </div>
        <div class="buttons" role="list" aria-label="buttons">
          <span :for={{b, i} <- Enum.with_index(d.state.buttons)} class={["btn-dot", b && "on"]} role="listitem">{i}<span :if={b} class="sr-only"> down</span></span>
        </div>
      </.card>

      <.card :if={@devices == []} title="No Game Controller Open">
        <.hint>Plug one into <strong>this machine</strong> (the one running the server). Game controllers and joysticks are opened automatically within 3 s.</.hint>
        <.kv :for={s <- @seen.devices} label={"#{Integer.to_string(s.vendor_id, 16)}:#{Integer.to_string(s.product_id, 16)}"} value={"#{s.product} · usage #{s.usage_page}/#{s.usage}#{if s.reading, do: " · reading", else: ""}"} />
      </.card>

      <%!-- a page action, so it's on the page: the toolbar is for getting around, help and STOP --%>
      <.row><.btn variant="ghost" phx-click="scan" aria-label="Scan for game controllers">Scan Now</.btn></.row>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # a pad we know by its parser's name; any other HID device by what it calls itself
  defp device_name(%{parser: "unknown HID device"} = d) do
    case d[:device] do
      %{product: p} when is_binary(p) and p != "" -> p
      _ -> "Unknown HID Device"
    end
  end

  defp device_name(d), do: d.parser

  defp axis_name(0), do: "X"
  defp axis_name(1), do: "Y"
  defp axis_name(i), do: to_string(i)

  defp bar_style(v) when is_number(v) do
    v = v |> max(-1.0) |> min(1.0)
    if v >= 0, do: "left:50%;width:#{v * 50}%", else: "left:#{50 + v * 50}%;width:#{-v * 50}%"
  end

  defp bar_style(_), do: "left:50%;width:0"

  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt2(x) when is_number(x), do: :erlang.float_to_binary(x * 1.0, decimals: 2)
  defp fmt2(_), do: Controller.Words.none()
end
