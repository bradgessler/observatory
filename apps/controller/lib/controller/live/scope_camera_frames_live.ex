defmodule Controller.ScopeCameraFramesLive do
  @moduledoc """
  The telescope camera's last frames, each on a page of its own: the list
  (newest first, the number, why and when over what it was asked for and
  what it found), and one frame's picture with its whole record, with the
  frames before and after it a tap away. The box keeps the last 20
  pictures; kept frames (Keep Frames) are FITS files on the Mac, with all
  of this in their headers.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{ScopeCamera, Settings}

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      ScopeCamera.subscribe()
      Settings.subscribe()
    end

    cam = ScopeCamera.find()
    {:ok, socket |> assign(night: Settings.get("night", false), cam: cam, frames: cam[:frames] || []) |> pick(params)}
  end

  @impl true
  def handle_params(params, _uri, socket), do: {:noreply, pick(socket, params)}

  @impl true
  def handle_info({:scope_camera, heard}, socket) do
    cam = ScopeCamera.prefer(socket.assigns.cam, heard)
    {:noreply, socket |> assign(cam: cam, frames: cam[:frames] || []) |> pick(%{"seq" => socket.assigns[:seq]})}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info(_, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  defp pick(socket, %{"seq" => seq}) when is_binary(seq) or is_integer(seq) do
    n = if is_integer(seq), do: seq, else: String.to_integer(seq)
    on = socket.assigns.cam[:node] || node()
    kept = ScopeCamera.frame(n, on)
    record = Enum.find(socket.assigns.frames, &(&1.seq == n)) || with({:ok, r, _} <- kept, do: r, else: (_ -> nil))
    assign(socket, seq: n, record: record, page_title: "Telescope Camera · Frame #{n}", kept?: match?({:ok, _, _}, kept))
  end

  defp pick(socket, _), do: assign(socket, seq: nil, record: nil, page_title: "Telescope Camera · Frames", kept?: false)

  @impl true
  def render(%{seq: nil} = assigns) do
    ~H"""
    <.page id="scope-camera-frames" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/telescope"} label="Telescope Camera" />
        <.title>Frames</.title>
        <.actions><.help href={~p"/docs/scope-camera"} label="the telescope camera" /><.stop /></.actions>
      </:header>

      <p class="hint">The last frames the camera took, newest first. Each has its own page: the frame, and what was known when it was taken.</p>

      <.items :if={@frames != []} label="the last frames, newest first">
        <.link_item :for={r <- @frames} navigate={~p"/cameras/telescope/frames/#{r.seq}"} label={frame_title(r)} detail={detail(r)} />
      </.items>
      <p :if={@frames == []} class="dim">No frames yet. Tap Live View on the camera page.</p>
    </.page>
    """
  end

  def render(assigns) do
    ~H"""
    <.page id="scope-camera-frame" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/telescope/frames"} label="Frames" />
        <.title>Frame {@seq}</.title>
        <.actions><.help href={~p"/docs/scope-camera"} label="the telescope camera" /><.stop /></.actions>
      </:header>

      <section class="scope-frame" aria-label={"frame #{@seq}"}>
        <img :if={@kept?} src={ScopeCamera.src_numbered(@cam, @seq)} alt={"Frame #{@seq}"} />
        <p :if={!@kept?} class="dim">The box keeps the last 20 frames; this one is gone. A kept frame is on the Mac as a FITS file.</p>
      </section>

      <.card :if={@record} title="What Was Known">
        <.items label="this frame's record">
          <.item :for={{label, value} <- rows(@record)} as="li" label={label} detail={value} />
        </.items>
      </.card>
      <p :if={!@record} class="dim">Nothing is known about frame {@seq} any more.</p>

      <.row>
        <.btn navigate={~p"/cameras/telescope/frames/#{@seq - 1}"}>Frame {@seq - 1}</.btn>
        <.btn :if={newer?(@frames, @seq)} navigate={~p"/cameras/telescope/frames/#{@seq + 1}"}>Frame {@seq + 1}</.btn>
      </.row>
    </.page>
    """
  end

  defp newer?(frames, seq), do: Enum.any?(frames, &(&1.seq > seq))

  defp frame_title(r), do: "Frame #{r.seq} · #{why_words(r.why)} · #{Calendar.strftime(r.at, "%H:%M:%S")} UTC"

  # a record says why it was taken: "live view", or "picture" for one asked for on its own
  defp why_words("picture"), do: "a single frame"
  defp why_words(why), do: why

  defp detail(%{ok: false} = r), do: "Failed: #{r.error}"

  defp detail(r) do
    stars = if r.stars > 0, do: "#{r.stars} stars, HFR #{r.hfr_px} px", else: "no stars"
    "#{r.exposure_ms} ms, gain #{r.gain}: background #{r.background} of 255, brightest #{r.max}, #{stars}"
  end

  # the record, a row each, in plain words
  defp rows(r) do
    [
      {"Taken", "#{Calendar.strftime(r.at, "%Y-%m-%d %H:%M:%S")} UTC, for #{why_words(r.why)}"},
      {"Exposure", "#{r.exposure_ms} ms, gain #{r.gain}, #{if r.stack > 1, do: "#{r.stack} exposures averaged", else: "1 exposure"}"},
      {"Camera mode", r.mode},
      r[:size] && {"Size", "#{r.size} pixels"},
      r[:ok] != false && {"Sky", "Background #{r.background} of 255, noise #{r.noise}, brightest pixel #{r.max}, #{r.saturated_pct}% at full white"},
      r[:ok] != false && {"Stars", if(r.stars > 0, do: "#{r.stars}, half-flux radius #{r.hfr_px} px", else: "None found")},
      r[:verdict] && {"Verdict", Controller.ScopeCamera.Image.verdict_words(r.verdict)},
      r[:grab_ms] && {"Time taken", "#{r.took_ms} ms: grab #{r.grab_ms} ms, measure #{r.measure_ms} ms"},
      r[:error] && {"Failed", r.error}
    ]
    |> Enum.filter(& &1)
  end

end
