defmodule Controller.AxesLive do
  @moduledoc """
  Optical axes: find the mount's axes in the camera picture by moving them a
  little and watching what moved. An experiment page — run it, look at the
  arrows and the pivot marks over the still, read what the fit says.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Optical.AxisScan
  alias Controller.Settings

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      AxisScan.subscribe()
      Settings.subscribe()
      send(self(), :rescan)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(night: Settings.get("night", false), nested: session["nested"] == true, selected: params["id"] || session["id"], mounts: [], notice: nil)
     |> assign(scan: AxisScan.status())
     |> rescan()
     |> load()}
  end

  defp rescan(socket) do
    mounts = Mount.list() |> Enum.map(& &1.id) |> Enum.sort()
    selected = if socket.assigns.selected in mounts, do: socket.assigns.selected, else: List.first(mounts)
    assign(socket, mounts: mounts, selected: selected)
  end

  defp load(socket) do
    assign(socket, result: socket.assigns.selected && AxisScan.result(socket.assigns.selected), camera: Watch.status())
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> load()}
  end

  def handle_info({:optical, status}, socket), do: {:noreply, socket |> assign(scan: status) |> load()}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "optical_axes", _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("run", _, socket) do
    case AxisScan.run(socket.assigns.selected) do
      :ok -> {:noreply, assign(socket, notice: "scanning — the mount will move ±1.5° on each axis")}
      {:error, :busy} -> {:noreply, assign(socket, notice: "a scan is already running")}
      {:error, why} -> {:noreply, assign(socket, notice: inspect(why))}
    end
  end

  def handle_event("clear", _, socket) do
    AxisScan.clear(socket.assigns.selected)
    {:noreply, load(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="axes" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/controls/watch"} label="Watch" />
        <.title>Optical Axes</.title>
        <.actions><.help href={~p"/docs/axes"} /></.actions>
      </:header>

      <.card title="Find the axes in the picture">
        <:aside><.badge on={@scan.running} warn={@scan.step == :failed}>{step_words(@scan)}</.badge></:aside>
        <.hint>Turns each axis 1.5° and back with the camera watching, then works out from what moved where the axis pivots in the picture. Experiment: an honest first look, not a calibration yet.</.hint>
        <.row>
          <.btn variant="primary" phx-click="run" disabled={@scan.running or is_nil(@selected) or is_nil(@camera.tool)}>Find the axes</.btn>
          <.btn :if={@result} class="btn-ghost" phx-click="clear">Forget this result</.btn>
        </.row>
        <.hint :if={is_nil(@camera.tool)}>No camera tool on this machine.</.hint>
        <.hint :if={@scan.error} class="err">{@scan.error}</.hint>
      </.card>

      <.card :if={@result} title={"Result · #{String.slice(@result["at"], 11, 5)} UTC"}>
        <div class="axes-pic">
          <img :if={@result["frame"]} src={~p"/watch/frames/#{@result["frame"]}"} alt="the frame before any move" />
          <svg viewBox={"0 0 #{@result["w"]} #{@result["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <%= for {axis, colour} <- [{"ra", "#4f8cff"}, {"dec", "#2ec27e"}] do %>
              <% ax = @result[axis] %>
              <line :for={v <- ax["vectors"]} x1={v["x"]} y1={v["y"]} x2={v["x"] + v["dx"] * 3} y2={v["y"] + v["dy"] * 3} stroke={colour} stroke-width="0.6" stroke-linecap="round" opacity="0.9" />
              <g :if={ax["fit"] && ax["fit"]["cx"]}>
                <circle cx={ax["fit"]["cx"]} cy={ax["fit"]["cy"]} r="4" fill="none" stroke={colour} stroke-width="1.2" />
                <line x1={ax["fit"]["cx"] - 7} y1={ax["fit"]["cy"]} x2={ax["fit"]["cx"] + 7} y2={ax["fit"]["cy"]} stroke={colour} stroke-width="1" />
                <line x1={ax["fit"]["cx"]} y1={ax["fit"]["cy"] - 7} x2={ax["fit"]["cx"]} y2={ax["fit"]["cy"] + 7} stroke={colour} stroke-width="1" />
              </g>
            <% end %>
          </svg>
        </div>
        <div :for={{axis, label} <- [{"ra", "RA · polar axis"}, {"dec", "Dec axis"}]} class="axes-row">
          <% ax = @result[axis] %>
          <strong class={"ax-#{axis}"}>{label}</strong>
          <span>{ax["words"]}</span>
          <span :if={ax["fit"]} class="dim">
            {length(ax["vectors"])} blocks moved ·
            {if ax["fit"]["cx"], do: "pivot at (#{round(ax["fit"]["cx"] * @result["scale"])}, #{round(ax["fit"]["cy"] * @result["scale"])}) px · "}
            spin {Float.round(ax["fit"]["quality"] / 1, 2)} · slide {Float.round(ax["fit"]["coherence"] / 1, 2)}
          </span>
          <span :if={!ax["fit"]} class="dim">nothing moved enough to measure</span>
        </div>
        <.hint>Arrows show where the picture moved when that axis turned (blue RA, green Dec), stretched 3×. A cross is the best-fit pivot when the motion looks like a spin. The numbers are in the original frame's pixels.</.hint>
      </.card>

      <p :if={@notice} id={"notice-#{:erlang.phash2(@notice)}"} class="notice">{@notice}</p>
    </.page>
    """
  end

  defp step_words(%{running: false, step: :done}), do: "done"
  defp step_words(%{running: false, step: :failed}), do: "failed"
  defp step_words(%{running: false}), do: "idle"
  defp step_words(%{step: :capture_before}), do: "first picture"
  defp step_words(%{step: {:move, ax}}), do: "turning #{ax}"
  defp step_words(%{step: {:capture, ax}}), do: "picture after #{ax}"
  defp step_words(%{step: {:analyse, ax}}), do: "looking at #{ax}"
  defp step_words(_), do: "working"
end
