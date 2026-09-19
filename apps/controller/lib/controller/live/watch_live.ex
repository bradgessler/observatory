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

  @strip 12

  defp load(socket) do
    status = Watch.status()

    assign(socket,
      status: status,
      devices: Watch.devices(),
      frame: status.latest,
      stamp: System.unique_integer([:positive]),
      history: Watch.history(limit: @strip),
      summary: Watch.history_summary(),
      # nil = follow the live frame; a name = pinned on one from the strip
      pinned: socket.assigns[:pinned]
    )
  end

  @impl true
  def handle_info({:watch, _meta}, socket), do: {:noreply, load(socket)}
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

  def handle_event("pin", %{"name" => name}, socket), do: {:noreply, assign(socket, pinned: name)}
  def handle_event("pin", _, socket), do: {:noreply, assign(socket, pinned: nil)}

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp pinned_entry(nil, _), do: nil
  defp pinned_entry(name, history), do: Enum.find(history, &(&1.name == name))

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
        <% pin = pinned_entry(@pinned, @history) %>
        <div class="watch-frame">
          <img :if={pin} src={~p"/watch/frames/#{pin.name}"} alt={"frame of the telescope from #{Calendar.strftime(pin.at, "%H:%M:%S")} UTC"} />
          <img :if={!pin and @frame} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="latest frame of the telescope" />
          <.hint :if={!pin and !@frame}>No frame yet. {if @status.tool, do: "Tap Capture.", else: "No capture tool on this machine (brew install imagesnap)."}</.hint>
        </div>
        <.hint :if={pin}><b>held on</b> {Calendar.strftime(pin.at, "%H:%M:%S")} UTC · {div(pin.bytes, 1024)} KB · <a href="#" phx-click="pin">back to live</a></.hint>
        <.hint :if={!pin and @frame}>{Calendar.strftime(@frame.at, "%H:%M:%S")} UTC · {@frame.device} · {div(@frame.bytes, 1024)} KB</.hint>

        <%!-- the recent past, newest first; tap one to hold it, tap again for live --%>
        <nav :if={@history != []} class="watch-strip" aria-label="recent frames">
          <a :for={e <- @history} href="#" class={e.name == @pinned && "on"} phx-click="pin" phx-value-name={if e.name == @pinned, do: nil, else: e.name}>
            <img src={~p"/watch/frames/#{e.name}"} alt="" loading="lazy" />
            <time datetime={DateTime.to_iso8601(e.at)}>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
          </a>
        </nav>
        <.hint :if={@summary.count > 0}>
          keeping {@summary.count} frames · {div(@summary.bytes, 1_048_576)} MB · back to {Calendar.strftime(@summary.oldest, "%H:%M:%S")} UTC
          (up to {@summary.policy.max_frames} frames or {div(@summary.policy.max_age_s, 60)} min, on disk)
        </.hint>
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
