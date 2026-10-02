defmodule Controller.CamerasLive do
  @moduledoc """
  Every camera, side by side: the telescope camera (in the focuser) and the
  observatory camera (watching the mount), each its latest picture, its
  name, and one line on how it is. Tap one for its page.

  Looking here keeps the observatory camera's stills coming, as its own page
  does. It doesn't turn on the telescope camera's live view, which changes
  the camera for everyone watching; its picture says how old it is, and Live
  View is a tap away on its page.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{ScopeCamera, Settings}

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      ScopeCamera.subscribe()
      Watch.subscribe()
      Settings.subscribe()
      # the ages in words
      :timer.send_interval(5_000, :tick)
      if safe(fn -> Watch.status().tool end, nil), do: safe(fn -> Watch.enable(true) end, nil)
    end

    {:ok, socket |> assign(page_title: "All Cameras", night: Settings.get("night", false), now: DateTime.utc_now()) |> load()}
  end

  defp load(socket) do
    assign(socket,
      cam: ScopeCamera.find(),
      watch: safe(fn -> Watch.status() end, %{}),
      stamp: System.unique_integer([:positive])
    )
  end

  @impl true
  def handle_info({:scope_camera, cam}, socket), do: {:noreply, assign(socket, cam: ScopeCamera.prefer(socket.assigns.cam, cam))}
  def handle_info({:watch, _}, socket), do: {:noreply, load(socket)}
  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info(_, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  @impl true
  def render(assigns) do
    latest = List.first(assigns.cam[:frames] || [])
    still = assigns.watch[:latest]
    assigns = assign(assigns, latest: latest, still: still)

    ~H"""
    <.page id="cameras" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="Cameras" />
        <.title>All Cameras</.title>
        <.actions><.help href={~p"/docs/cameras"} label="cameras" /><.stop /></.actions>
      </:header>

      <ul class="camera-grid" role="list">
        <li>
          <.link navigate={~p"/cameras/telescope"} class="camera-tile">
            <span class="camera-pic">
              <img :if={picture?(@cam, @latest)} src={ScopeCamera.src(@cam, @latest.seq)} alt={"Telescope camera, frame #{@latest.seq}"} />
              <span :if={!picture?(@cam, @latest)} class="camera-none">{if @cam[:camera], do: "No picture yet", else: "Not plugged in"}</span>
            </span>
            <span class="camera-text">
              <strong>Telescope Camera</strong>
              <small>{telescope_line(@cam, @latest, @now)}</small>
            </span>
          </.link>
        </li>
        <li>
          <.link navigate={~p"/cameras/observatory"} class="camera-tile">
            <span class="camera-pic">
              <img :if={@still} src={~p"/watch/latest.jpg?#{[v: @stamp]}"} alt="Observatory camera, the latest still of the mount" />
              <span :if={!@still} class="camera-none">{if @watch[:tool], do: "No picture yet", else: "No camera on this machine"}</span>
            </span>
            <span class="camera-text">
              <strong>Observatory Camera</strong>
              <small>{observatory_line(@watch, @still, @now)}</small>
            </span>
          </.link>
        </li>
      </ul>
    </.page>
    """
  end

  defp picture?(cam, latest), do: cam[:camera] != nil and is_map(latest) and latest[:ok] != false and not (cam[:video] == true)

  @doc false
  # one line on the telescope camera: whether it's there, live, and how old its picture is
  def telescope_line(%{down: true}, _, _), do: "The camera part of this machine isn't running"
  def telescope_line(%{camera: nil}, _, _), do: "Plug it into this machine's USB; it shows up by itself"
  def telescope_line(%{video: true}, _, _), do: "Video on its page"
  def telescope_line(%{live: true}, %{seq: seq}, _), do: "Live · frame #{seq}"
  def telescope_line(_, %{seq: seq, at: at}, now), do: "Frame #{seq} · #{ago(at, now)} · Live View is off"
  def telescope_line(_, _, _), do: "Live View is off"

  @doc false
  def observatory_line(%{last_error: e}, nil, _) when is_binary(e), do: e
  def observatory_line(%{tool: nil}, _, _), do: "Plug a webcam into this machine; it shows up by itself"
  def observatory_line(%{streaming: true}, _, _), do: "Live video on its page"
  def observatory_line(_, %{at: at}, now), do: "Still from #{ago(at, now)}"
  def observatory_line(_, _, _), do: "Waiting for the first still"

  defp ago(%DateTime{} = at, now) do
    case DateTime.diff(now, at) do
      s when s < 10 -> "just now"
      s when s < 90 -> "#{s} s ago"
      s when s < 5400 -> "#{div(s, 60)} min ago"
      s -> "#{div(s, 3600)} h ago"
    end
  end

  defp ago(_, _), do: "a while ago"

  defp safe(fun, default) do
    fun.()
  catch
    _, _ -> default
  end
end
