defmodule Controller.WatchLive do
  @moduledoc """
  Eyes on the mount: the latest frame from a camera on the server machine,
  refreshed on a timer or on demand. Answers "is it about to wrap a cable?"
  from anywhere.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      Watch.subscribe()
      Settings.subscribe()
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       mount_id: params["id"] || session["id"],
       notice: nil
     )
     |> load()}
  end

  defp load(socket) do
    status = Watch.status()
    assign(socket, status: status, devices: Watch.devices(), frame: status.latest, stamp: System.unique_integer([:positive]))
  end

  @impl true
  def handle_info({:watch, meta}, socket), do: {:noreply, assign(socket, frame: meta, stamp: System.unique_integer([:positive]), status: Watch.status())}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("capture", _, socket) do
    case Watch.capture() do
      %{} -> {:noreply, load(socket)}
      {:error, why} -> {:noreply, socket |> assign(notice: "capture failed: #{why}") |> load()}
    end
  end

  def handle_event("live", _, socket) do
    Watch.enable(not socket.assigns.status.enabled)
    {:noreply, load(socket)}
  end

  def handle_event("select", %{"device" => d}, socket) do
    Watch.select(d)
    {:noreply, load(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="watch" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/watch"} label="bench" />
        <.title>watch</.title>
        <.actions><.help href={~p"/docs/devices"} /></.actions>
      </:header>

      <.card>
        <:aside>
          <.badge on={@status.enabled}>{if @status.enabled, do: "live · every #{div(@status.interval, 1000)} s", else: "paused"}</.badge>
        </:aside>
        <div class="watch-frame">
          <img :if={@frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
          <.hint :if={!@frame}>No frame yet. {if @status.tool, do: "Tap Capture.", else: "No capture tool on this machine (brew install imagesnap)."}</.hint>
        </div>
        <.hint :if={@frame}>{Calendar.strftime(@frame.at, "%H:%M:%S")} UTC · {@frame.device} · {div(@frame.bytes, 1024)} KB</.hint>
        <.row>
          <.btn phx-click="capture" disabled={is_nil(@status.tool)}>Capture</.btn>
          <.btn phx-click="live" on={@status.enabled} disabled={is_nil(@status.tool)}>{if @status.enabled, do: "Pause", else: "Live"}</.btn>
        </.row>
        <form :if={@devices != []} phx-change="select" class="row">
          <select name="device" class="field">
            <option :for={d <- @devices} value={d} selected={d == @status.device}>{d}</option>
          </select>
        </form>
        <.hint :if={@status.last_error}>last error: {@status.last_error}</.hint>
      </.card>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end
end
