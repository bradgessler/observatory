defmodule Controller.FramesLive do
  @moduledoc """
  The recent past: every still the camera kept, newest first. Tap one to see
  it big; the list keeps growing underneath while you look.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      Watch.subscribe()
      Settings.subscribe()
    end

    {:ok,
     socket
     |> assign(page_title: "Recent Frames", night: Settings.get("night", false), pinned: params["frame"])
     |> load()}
  end

  defp load(socket) do
    assign(socket, history: Watch.history(limit: 120), summary: Watch.history_summary())
  end

  @impl true
  def handle_info({:watch, _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("pin", %{"name" => name}, socket), do: {:noreply, assign(socket, pinned: name)}
  def handle_event("pin", _, socket), do: {:noreply, assign(socket, pinned: nil)}

  @impl true
  def render(assigns) do
    assigns = assign(assigns, pin: Enum.find(assigns.history, &(&1.name == assigns.pinned)))

    ~H"""
    <.page id="frames" night={@night}>
      <:header>
        <.back navigate={~p"/controls/watch"} label="Watch" />
        <.title>Recent Frames</.title>
        <.actions><.help href={~p"/docs/watch"} label="watching" /></.actions>
      </:header>

      <.card :if={@pin}>
        <div class="watch-frame">
          <img src={~p"/watch/frames/#{@pin.name}"} alt={"frame from #{Calendar.strftime(@pin.at, "%H:%M:%S")} UTC"} />
        </div>
        <.hint>{Calendar.strftime(@pin.at, "%H:%M:%S")} UTC · {div(@pin.bytes, 1024)} KB · <button type="button" class="linklike" phx-click="pin">close the big frame</button></.hint>
      </.card>

      <.hint :if={@history == []}>Nothing kept yet. Frames arrive whenever the camera captures: timed stills, a tap on Capture, or a running stream.</.hint>

      <ul :if={@history != []} class="frame-grid" role="list" aria-label="recent frames, newest first">
        <li :for={e <- @history}>
          <button type="button" class={e.name == @pinned && "on"} phx-click="pin" phx-value-name={if e.name == @pinned, do: nil, else: e.name} aria-pressed={to_string(e.name == @pinned)} aria-label={"frame from #{Calendar.strftime(e.at, "%H:%M:%S")} UTC, show big"}>
            <img src={~p"/watch/frames/#{e.name}"} alt="" loading="lazy" />
            <time datetime={DateTime.to_iso8601(e.at)}>{Calendar.strftime(e.at, "%H:%M:%S")}</time>
          </button>
        </li>
      </ul>

      <.hint :if={@summary.count > 0}>
        {@summary.count} frames · {div(@summary.bytes, 1_048_576)} MB · oldest {Calendar.strftime(@summary.oldest, "%H:%M:%S")} UTC ·
        kept up to {@summary.policy.max_frames} frames or {div(@summary.policy.max_age_s, 60)} min, on disk under ~/.observatory/watch/frames
      </.hint>
    </.page>
    """
  end
end
