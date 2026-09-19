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
    id = socket.assigns.selected
    assign(socket, result: id && AxisScan.result(id), camera: Watch.status(), predicted: id && predicted(id))
  end

  # What the orb's geometry says each axis should look like from where the
  # orb's viewer stands (Setup › view from): the angle of its projection.
  # If the webcam stands roughly where the orb's viewer does, the camera's
  # measured line and this should agree — a first calibration check.
  defp predicted(id) do
    with ref when not is_nil(ref) <- Enum.find(Mount.list(), &(&1.id == id)),
         %{connected: true} = snap <- Mount.snapshot(ref) do
      scene = Controller.OrbLive.scene(snap, Controller.Sky.Pointing.context(DateTime.utc_now(), id))
      %{"ra" => angle_of(scene.ra.head, scene.ra.tail), "dec" => angle_of(scene.dec.head, scene.dec.tail), "from" => round(Settings.get("orb_view_az", 150.0) / 1)}
    else
      _ -> nil
    end
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end

  defp angle_of({hx, hy, _}, {tx, ty, _}), do: line_angle(hx - tx, hy - ty)

  # undirected line angle in degrees, 0..180, screen y-down
  defp line_angle(dx, dy) do
    a = :math.atan2(dy, dx) * 180 / :math.pi()
    a = if a < 0, do: a + 180, else: a
    Float.round(a, 0)
  end

  defp measured(%{"line" => %{"ux" => ux, "uy" => uy}}), do: line_angle(ux, uy)
  defp measured(_), do: nil

  defp apart(a, b) when is_number(a) and is_number(b) do
    d = abs(a - b)
    round(min(d, 180 - d))
  end

  defp apart(_, _), do: nil

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
      :ok -> {:noreply, assign(socket, notice: "scanning — the mount will move ±3° on each axis")}
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
        <.hint>Turns each axis 3° and back with the camera watching, then works out from what moved where the axis pivots in the picture. Experiment: an honest first look, not a calibration yet.</.hint>
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
            <defs>
              <marker id="ah-ra" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#4f8cff" /></marker>
              <marker id="ah-dec" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#2ec27e" /></marker>
            </defs>
            <%= for {axis, colour} <- [{"ra", "#4f8cff"}, {"dec", "#2ec27e"}] do %>
              <% ax = @result[axis] %>
              <line :for={v <- ax["vectors"]} x1={v["x"]} y1={v["y"]} x2={v["x"] + v["dx"] * 4} y2={v["y"] + v["dy"] * 4} stroke={colour} stroke-width="1.6" stroke-linecap="round" opacity="0.95" marker-end={"url(#ah-#{axis})"} />
              <%!-- the axis direction across the picture, when the motion is a slide --%>
              <line :if={ax["line"] && ax["fit"] && ax["fit"]["coherence"] > 0.5} x1={ax["line"]["x"] - ax["line"]["ux"] * 2000} y1={ax["line"]["y"] - ax["line"]["uy"] * 2000} x2={ax["line"]["x"] + ax["line"]["ux"] * 2000} y2={ax["line"]["y"] + ax["line"]["uy"] * 2000} stroke={colour} stroke-width="2" stroke-dasharray="10 8" opacity="0.8" />
              <g :if={ax["fit"] && ax["fit"]["cx"]}>
                <circle cx={ax["fit"]["cx"]} cy={ax["fit"]["cy"]} r="9" fill="none" stroke={colour} stroke-width="2" />
                <line x1={ax["fit"]["cx"] - 16} y1={ax["fit"]["cy"]} x2={ax["fit"]["cx"] + 16} y2={ax["fit"]["cy"]} stroke={colour} stroke-width="1.6" />
                <line x1={ax["fit"]["cx"]} y1={ax["fit"]["cy"] - 16} x2={ax["fit"]["cx"]} y2={ax["fit"]["cy"] + 16} stroke={colour} stroke-width="1.6" />
              </g>
            <% end %>
          </svg>
        </div>
        <div :for={{axis, label} <- [{"ra", "RA · polar axis"}, {"dec", "Dec axis"}]} class="axes-row">
          <% ax = @result[axis] %>
          <strong class={"ax-#{axis}"}>{label}</strong>
          <span>{ax["words"]}</span>
          <span :if={ax["fit"]} class="dim">
            {length(ax["vectors"])} blocks moved{if (ax["dropped"] || 0) > 0, do: " (#{ax["dropped"]} odd ones ignored)"} ·
            {if ax["fit"]["cx"], do: "pivot at (#{round(ax["fit"]["cx"] * @result["scale"])}, #{round(ax["fit"]["cy"] * @result["scale"])}) px · "}
            spin {Float.round(ax["fit"]["quality"] / 1, 2)} · slide {Float.round(ax["fit"]["coherence"] / 1, 2)}
          </span>
          <span :if={!ax["fit"]} class="dim">nothing moved enough to measure</span>
          <%!-- the line only means something for a slide; a turn has a pivot, not a direction --%>
          <span :if={ax["line"] && @predicted && ax["fit"] && ax["fit"]["coherence"] > 0.5} class="dim">
            camera sees this axis at {round(measured(ax))}° · the orb, viewed from {@predicted["from"]}°, draws it at {round(@predicted[axis])}° · {apart(measured(ax), @predicted[axis])}° apart
          </span>
        </div>
        <.hint :if={@predicted}>The comparison with the orb only means something if the orb's viewpoint (Orb › from N/E/S/W, or Setup) is roughly where the camera stands; camera roll and height are not accounted for yet.</.hint>
        <.hint>Arrows show where the picture moved when that axis turned (blue RA, green Dec), stretched 4×. A dashed line is the axis's direction across the picture when the motion is a slide; a cross is the best-fit pivot when it turns. Numbers are in the original frame's pixels.</.hint>
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
