defmodule Controller.ScopeCameraSettingsLive do
  @moduledoc """
  The telescope camera's knobs, off the camera page: exposure (how long each
  picture collects light), gain, how many frames are averaged into one
  picture, whether pictures are kept (to the card, then the Mac), and video
  instead of pictures. Kept in Settings, so every phone sees the same.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{ScopeCamera, Settings}

  @exposures [100, 250, 500, 1000, 2000]
  @stacks [1, 2, 4, 8]
  @gains [0, 25, 50, 75, 100]

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      ScopeCamera.subscribe()
      Settings.subscribe()
    end

    cam = ScopeCamera.find()

    {:ok,
     assign(socket,
       page_title: "Telescope Camera · Settings",
       night: Settings.get("night", false),
       cam: cam,
       exposures: @exposures,
       stacks: @stacks,
       gains: @gains,
       keep_last: on_camera(cam, :get, ["frames_keep_last", 1000]),
       notice: nil
     )}
  end

  @impl true
  def handle_info({:scope_camera, cam}, socket), do: {:noreply, assign(socket, cam: ScopeCamera.prefer(socket.assigns.cam, cam))}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "frames_keep_last", _}, socket), do: {:noreply, assign(socket, keep_last: on_camera(socket.assigns.cam, :get, ["frames_keep_last", 1000]))}
  def handle_info(_, socket), do: {:noreply, socket}

  @impl true
  def handle_event("set", params, socket) do
    changes =
      for {k, v} <- params, k in ~w(exposure_ms gain stack), {n, _} <- [Integer.parse(to_string(v))], do: {String.to_existing_atom(k), n}

    ScopeCamera.set(changes, node_of(socket))
    {:noreply, socket}
  end

  def handle_event("keep_last", %{"n" => n}, socket) do
    v = if n == "all", do: "all", else: String.to_integer(n)
    on_camera(socket.assigns.cam, :put, ["frames_keep_last", v])
    {:noreply, assign(socket, keep_last: v)}
  end

  def handle_event("keep", %{"on" => on}, socket) do
    ScopeCamera.keep(on == "true", node_of(socket))
    {:noreply, socket}
  end

  def handle_event("video", %{"on" => on}, socket) do
    notice =
      case ScopeCamera.video(on == "true", node_of(socket)) do
        :ok -> nil
        {:error, :no_real_camera} -> "Video needs a real camera plugged in"
        {:error, e} -> "Video didn't start: " <> Controller.Words.error(e)
      end

    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  defp node_of(socket), do: socket.assigns.cam[:node] || node()

  # a setting kept on the machine the camera is on (its spool keeps the frames)
  defp on_camera(cam, fun, args) do
    case cam[:node] || node() do
      n when n == node() -> apply(Settings, fun, args)
      n -> :erpc.call(n, Settings, fun, args, 5_000)
    end
  catch
    _, _ -> if fun == :get, do: List.last(args), else: :error
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="scope-camera-settings" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/telescope"} label="Telescope Camera" />
        <.title>Settings</.title>
        <.actions><.help href={~p"/docs/scope-camera"} label="the telescope camera" /><.stop /></.actions>
      </:header>

      <.card title="Exposure">
        <.seg label="exposure in milliseconds">
          <:opt :for={ms <- @exposures} on={@cam[:settings]["exposure_ms"] == ms} click="set" value={%{exposure_ms: ms}} disabled={@cam[:max_exposure_ms] && ms > @cam.max_exposure_ms}>{ms} ms</:opt>
        </.seg>
        <p class="dim">How long each exposure collects light. Live View shows about one frame per exposure, plus half a second to measure it: longer finds fainter stars, shorter answers sooner.{limit(@cam[:max_exposure_ms])}</p>
      </.card>

      <.card :if={@cam[:has_gain] or @cam[:sim]} title="Gain">
        <.seg label="gain">
          <:opt :for={g <- @gains} on={@cam[:settings]["gain"] == g} click="set" value={%{gain: g}}>{g}</:opt>
        </.seg>
        <p class="dim">Brightens the frame, and its noise with it.</p>
      </.card>

      <.card title="Exposures Per Frame">
        <.seg label="exposures averaged into each frame">
          <:opt :for={n <- @stacks} on={@cam[:settings]["stack"] == n} click="set" value={%{stack: n}}>{n}</:opt>
        </.seg>
        <p class="dim">Averaging (stacking) exposures shows fainter stars with less noise, and takes that many times as long. <.link href={~p"/docs/glossary#stack"}>What's stacking?</.link></p>
      </.card>

      <.card title="Keep Frames">
        <p class="dim">Every frame goes to the box's SD card, then to the Mac.</p>
        <p :if={@cam[:keep]} class="find-line" role="status">{@cam[:kept]} kept{if (@cam[:not_kept] || 0) > 0, do: ", #{@cam[:not_kept]} dropped for room", else: ""}</p>
        <.row>
          <.btn on={@cam[:keep]} phx-click="keep" phx-value-on={to_string(!@cam[:keep])}>{if @cam[:keep], do: "Keeping Frames", else: "Keep Frames"}</.btn>
        </.row>
        <.seg label="frames kept on the SD card, newest first">
          <:opt :for={n <- [100, 1000, 10_000, "all"]} on={@keep_last == n} click="keep_last" value={%{n: n}}>{if n == "all", do: "All", else: "Last #{n}"}</:opt>
        </.seg>
        <p class="dim">The SD card keeps the newest; older ones go first, ones already on the Mac before ones that aren't.</p>
        <.items label="where the frames go">
          <.link_item navigate={~p"/queues"} label="Queues" detail="Each step, from the box's SD card to the Mac, and which one is slow" />
        </.items>
      </.card>

      <.card :if={!@cam[:sim]} title="Video">
        <p class="dim">Smooth video on the phone instead of frames, a few seconds behind; no focus readings or Auto Align while it's on.</p>
        <.row>
          <.btn on={@cam[:video]} phx-click="video" phx-value-on={to_string(!@cam[:video])}>{if @cam[:video], do: "Video On", else: "Video"}</.btn>
        </.row>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp limit(nil), do: ""
  defp limit(ms), do: " This camera goes up to #{round(ms)} ms."

end
