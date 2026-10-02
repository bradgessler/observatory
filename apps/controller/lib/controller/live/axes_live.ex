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
      Watch.subscribe()
      send(self(), :rescan)
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(page_title: "Optical Axes", night: Settings.get("night", false), nested: session["nested"] == true, selected: params["id"] || session["id"] || session["telescope"], mounts: [], notice: nil)
     |> assign(scan: AxisScan.status(), still_v: 0, run_started: nil)
     |> rescan()
     |> load()}
  end

  defp rescan(socket) do
    mounts = Mount.list() |> Enum.map(& &1.id) |> Enum.sort()
    selected = if socket.assigns.selected in mounts, do: socket.assigns.selected, else: Mount.default(mounts)
    assign(socket, mounts: mounts, selected: selected)
  end

  defp load(socket) do
    id = socket.assigns.selected
    assign(socket, result: id && AxisScan.result(id), camera: Watch.status(), predicted: id && predicted(id), homed: id != nil and homed?(id))
  end

  # the soft limits that keep a scan honest are only armed once home is set
  defp homed?(id) do
    case Enum.find(Mount.list(), &(&1.id == id)) do
      nil -> false
      ref -> match?(%{homed: true}, Mount.snapshot(ref))
    end
  catch
    :exit, _ -> false
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
  def handle_params(params, _uri, socket), do: {:noreply, assign(socket, details: params["details"] == "1")}

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> load()}
  end

  def handle_info({:optical, status}, socket) do
    started =
      cond do
        status.running and socket.assigns.run_started == nil -> System.monotonic_time(:second)
        status.running -> socket.assigns.run_started
        true -> nil
      end

    {:noreply, socket |> assign(scan: status, run_started: started) |> load()}
  end

  # a new still: the running view shows the camera's latest picture
  def handle_info({:watch, _}, socket), do: {:noreply, assign(socket, still_v: socket.assigns.still_v + 1)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "optical_axes", _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("run", _, socket) do
    case AxisScan.run(socket.assigns.selected) do
      :ok -> {:noreply, assign(socket, notice: "Scanning: the mount will move ±3° on each axis")}
      {:error, why} -> {:noreply, assign(socket, notice: refused(why))}
    end
  end

  def handle_event("sweep", %{"range" => range}, socket) do
    # the range comes from the browser: only one we offer
    half =
      case Float.parse(range) do
        {h, _} -> Enum.find(AxisScan.ranges(), &(&1 == h))
        :error -> nil
      end

    case half && AxisScan.sweep(socket.assigns.selected, range: half) do
      nil -> {:noreply, assign(socket, notice: "That sweep range is not one on offer")}
      :ok -> {:noreply, assign(socket, notice: "Sweeping: five positions per axis, ±#{round(half)}°, about three minutes")}
      {:error, why} -> {:noreply, assign(socket, notice: refused(why))}
    end
  end

  def handle_event("refine", _, socket) do
    case AxisScan.refine(socket.assigns.selected, range: 6.0) do
      :ok -> {:noreply, assign(socket, notice: "Refining: a sweep every few minutes until you stop it")}
      {:error, why} -> {:noreply, assign(socket, notice: refused(why))}
    end
  end

  def handle_event("stop_refining", _, socket) do
    AxisScan.stop_refining()
    {:noreply, assign(socket, notice: "This run finishes, then it stops")}
  end

  def handle_event("cancel", _, socket) do
    AxisScan.cancel()
    {:noreply, assign(socket, notice: "Cancelled; going back to where it started")}
  end

  def handle_event("clear", _, socket) do
    AxisScan.clear(socket.assigns.selected)
    {:noreply, load(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp refused(:busy), do: "A scan is already running"
  defp refused(:no_mount), do: "No mount to scan"
  defp refused(why) when is_binary(why), do: why
  defp refused(why), do: Controller.Words.error(why)

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="axes" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section="Alignment" />
        <.title>Optical Axes</.title>
        <.actions><.help href={~p"/docs/axes"} label="the optical axes" /><.stop /></.actions>
      </:header>

      <%!-- the procedure: one key, a line that says what it is doing, and an answer --%>
      <.card title="Find the Axes">
        <:aside><span role="status" aria-live="polite"><.badge on={@scan.running} warn={@scan.step in [:failed, :cancelled]}>{step_words(@scan)}</.badge></span></:aside>
        <% cannot = @scan.running or is_nil(@selected) or is_nil(@camera.tool) or not @homed %>
        <.hint>Turns each axis a few degrees with the camera watching and works out where the two axes are in the picture. The mount comes back to where it started.</.hint>
        <div :if={@scan.running} class="state-line" role="status" aria-live="polite">
          <strong>{step_words(@scan)}</strong>
          <span class="dim">{if @scan[:loop], do: "Refining: run after run until you stop it", else: "About ten minutes"} · STOP on any page ends it</span>
        </div>
        <.row :if={!@scan.running}>
          <.btn variant="primary" phx-click="sweep" phx-value-range="6.0" disabled={cannot}>Find the Axes · 10 min</.btn>
          <.btn phx-click="refine" disabled={cannot}>Keep Refining</.btn>
        </.row>
        <.row :if={@scan.running}>
          <.btn :if={@scan[:loop]} phx-click="stop_refining">Stop After This Run</.btn>
          <.btn phx-click="cancel">Cancel and Go Back</.btn>
        </.row>
        <.row :if={!@scan.running}>
          <.btn variant="ghost" phx-click="run" disabled={cannot}>Quick Look · 1 min</.btn>
          <.btn variant="ghost" phx-click="sweep" phx-value-range="20.0" disabled={cannot}>Wide Sweep · 20 min</.btn>
        </.row>
        <.hint :if={is_nil(@camera.tool)}>No camera tool on this machine.</.hint>
        <.hint :if={@selected && !@homed}>Set home first (<.link navigate={~p"/setup/#{@selected}"}>Setup</.link>): the soft limits that keep a scan safe are only armed once the mount knows where it is.</.hint>
        <.hint :if={@scan.error} class="err" role="alert">{@scan.error}</.hint>
      </.card>

      <%!-- while it runs: the camera's latest picture, what it is doing, which positions are done,
           and the spots' tracks and fitted lines drawn over the picture as each one lands --%>
      <% im = @scan[:interim] || %{} %>
      <% first = im["ra"] || im["dec"] %>
      <.card :if={@scan.running && !@details} title="Running">
        <div class="axes-pic">
          <img src={~p"/watch/latest.jpg?#{[v: @still_v]}"} alt="the Observatory Camera's latest still of the mount" />
          <svg :if={first} viewBox={"0 0 #{first["w"]} #{first["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <%= for {axis, colour} <- [{"ra", "var(--accent)"}, {"dec", "var(--on)"}], im[axis] do %>
              <polyline :for={t <- im[axis]["tracks"] || []} points={Enum.map_join(t, " ", fn [x, y] -> "#{x},#{y}" end)} fill="none" stroke={colour} stroke-width="1.2" opacity="0.85" />
            <% end %>
            <%= for {axis, colour, dash, name} <- [{"ra", "var(--accent)", "12 8", "RA"}, {"dec", "var(--on)", "4 4", "Dec"}], f = im[axis] && im[axis]["fit"], ll = f && long_line(f, first["w"], first["h"]), ll do %>
              <line x1={ll.x1} y1={ll.y1} x2={ll.x2} y2={ll.y2} stroke={colour} stroke-width="3" stroke-dasharray={dash} />
              <text x={ll.lx} y={ll.ly} fill={colour} font-size={div(first["w"], 28)} font-weight="700">{name}</text>
            <% end %>
          </svg>
        </div>
        <div class="state-line" role="status" aria-live="polite">
          <strong>{doing_words(@scan)}</strong>
          <span class="dim">{elapsed_words(@scan[:started_at] || @run_started)} · the mount comes back to where it started · STOP on any page ends it</span>
        </div>
        <div :for={{axis, label} <- [{"ra", "RA axis"}, {"dec", "Dec axis"}]} class="run-axis">
          <span class="run-dots" aria-label={"#{label}: #{positions_done(@scan, axis)} of 5 positions"}>
            <i :for={i <- 1..5} class={["run-dot", i <= positions_done(@scan, axis) && "on", i == positions_done(@scan, axis) + 1 && running_axis?(@scan, axis) && "now"]}></i>
          </span>
          <div class="state-line">
            <strong>{label} · {cond do im[axis] && im[axis]["fit"] -> answer_across(nil, im[axis]["fit"]); im[axis] -> "#{length(im[axis]["tracks"] || [])} spots on the move"; running_axis?(@scan, axis) -> "turning, taking pictures"; true -> "waiting its turn" end}</strong>
            <span :if={im[axis] && im[axis]["fit"]} class="dim">{im[axis]["fit"]["n"]} spots · arcs fit to {im[axis]["fit"]["rms_px"]} px · will settle as positions come in</span>
          </div>
        </div>
      </.card>

      <%!-- the answer: the two axes drawn on the picture, one sentence each --%>
      <% sw = @result && @result["sweep"] %>
      <% pair = sw && sw["pair"] %>
      <.card :if={sw && !@details && !(@scan.running && first)} title={"Where the Axes Are · #{String.slice(sw["at"], 11, 5)} UTC"}>
        <div class="axes-pic">
          <img :if={sw["ra"]["frames"] != []} src={~p"/watch/frames/#{hd(sw["ra"]["frames"])}"} alt="the mount, with the two fitted axes drawn over it" />
          <svg viewBox={"0 0 #{sw["ra"]["w"]} #{sw["ra"]["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <%= for {axis, colour} <- [{"ra", "var(--accent)"}, {"dec", "var(--on)"}] do %>
              <polyline :for={t <- sw[axis]["tracks"] || []} points={Enum.map_join(t, " ", fn [x, y] -> "#{x},#{y}" end)} fill="none" stroke={colour} stroke-width="1" opacity="0.45" />
            <% end %>
            <%= for {axis, colour, dash, name} <- [{"ra", "var(--accent)", "12 8", "RA"}, {"dec", "var(--on)", "4 4", "Dec"}] do %>
              <% pf = pair && pair[if(axis == "ra", do: "polar", else: "dec")] %>
              <% lf = if(pf && pf["line"], do: pf, else: sw[axis]["fit"]) %>
              <% ll = lf && long_line(lf, sw["ra"]["w"], sw["ra"]["h"]) %>
              <%= if ll do %>
                <line x1={ll.x1} y1={ll.y1} x2={ll.x2} y2={ll.y2} stroke={colour} stroke-width="3" stroke-dasharray={dash} />
                <text x={ll.lx} y={ll.ly} fill={colour} font-size={div(sw["ra"]["w"], 28)} font-weight="700">{name}</text>
              <% end %>
            <% end %>
          </svg>
        </div>
        <div class="state-line">
          <strong>RA axis · {answer_across(pair && pair["polar"], sw["ra"]["fit"])}</strong>
          <span class="dim">{answer_depth(pair && pair["polar"], sw["ra"]["fit"])}</span>
        </div>
        <div class="state-line">
          <strong>Dec axis · {answer_across(pair && pair["dec"], sw["dec"]["fit"])}</strong>
          <span class="dim">{answer_depth(pair && pair["dec"], sw["dec"]["fit"])}</span>
        </div>
        <div class="state-line">
          <strong>{confidence_words(sw)}</strong>
          <span class="dim">The direction across the picture is the part one camera can measure; how far in or out needs a second camera</span>
        </div>
        <.row>
          <.btn :if={@selected} navigate={~p"/cameras/observatory"}>See Them on the Observatory Camera ›</.btn>
          <.btn variant="ghost" patch={~p"/controls/watch/axes/#{@selected}?details=1"}>All the Numbers ›</.btn>
        </.row>
      </.card>

      <.card :if={!sw && @result && @result["ra"] && !@details} title={"Quick Look · #{String.slice(@result["at"], 11, 5)} UTC"}>
        <div class="state-line">
          <strong>RA axis · {@result["ra"]["words"]}</strong>
        </div>
        <div class="state-line">
          <strong>Dec axis · {@result["dec"]["words"]}</strong>
        </div>
        <.hint>A quick look only says how each axis moves the picture. Find the axes for the lines.</.hint>
        <.row><.btn variant="ghost" patch={~p"/controls/watch/axes/#{@selected}?details=1"}>All the Numbers ›</.btn></.row>
      </.card>

      <%= if @details do %>
      <.row>
        <.btn variant="ghost" patch={~p"/controls/watch/axes/#{@selected}"}>‹ Back to the Answer</.btn>
        <.btn :if={@result} variant="ghost" phx-click="clear" data-confirm="Forget the axis scan results for this mount?">Forget These Results</.btn>
      </.row>
      <%!-- the sweep: the axis in space, with margins --%>
      <% sw = @result && @result["sweep"] %>
      <.card :if={sw} title={"Sweep · #{String.slice(sw["at"], 11, 5)} UTC"}>
        <div class="axes-pic">
          <img :if={sw["ra"]["frames"] != []} src={~p"/watch/frames/#{hd(sw["ra"]["frames"])}"} alt="the first frame of the sweep" />
          <%!-- the tested inks, and a dash pattern per axis, so RA and Dec are told apart by more than colour --%>
          <svg viewBox={"0 0 #{sw["ra"]["w"]} #{sw["ra"]["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <%= for {axis, colour, dash} <- [{"ra", "var(--accent)", "12 8"}, {"dec", "var(--on)", "4 4"}] do %>
              <% ax = sw[axis] %>
              <polyline :for={t <- ax["tracks"]} points={Enum.map_join(t, " ", fn [x, y] -> "#{x},#{y}" end)} fill="none" stroke={colour} stroke-width="1.2" opacity="0.9" />
              <% pf = sw["pair"] && sw["pair"][if(axis == "ra", do: "polar", else: "dec")] %>
              <% lf = pf || ax["fit"] %>
              <line :if={lf} x1={lf["line"] |> hd() |> hd()} y1={lf["line"] |> hd() |> Enum.at(1)} x2={lf["line"] |> Enum.at(1) |> hd()} y2={lf["line"] |> Enum.at(1) |> Enum.at(1)} stroke={colour} stroke-width="2.4" stroke-dasharray={dash} />
            <% end %>
          </svg>
        </div>
        <%!-- both axes fitted together, perpendicular by construction: the number that matters --%>
        <% pair = sw["pair"] %>
        <div :if={pair} class="axes-row">
          <strong>Both axes together (perpendicular by construction)</strong>
          <span>
            RA axis <b>{pair["polar"]["image_angle_deg"]}° ± {margin(pair["polar"]["image_angle_sd_deg"], nil)}°</b> across the picture, <b>{abs(pair["polar"]["tilt_deg"])}° ± {margin(pair["polar"]["tilt_sd_deg"], nil)}°</b> out of it ·
            Dec axis <b>{pair["dec"]["image_angle_deg"]}°</b> across, <b>{abs(pair["dec"]["tilt_deg"])}°</b> out · arcs fit to {pair["rms_px"]} px
          </span>
          <span class="dim">
            Camera's reading of each commanded step · RA: {Enum.map_join(pair["steps"]["ra"], " · ", fn s -> "#{s["commanded_deg"]}→#{s["measured_deg"]}" end)} (strays {pair["step_error_deg"]["ra"]}°) ·
            Dec: {Enum.map_join(pair["steps"]["dec"], " · ", fn s -> "#{s["commanded_deg"]}→#{s["measured_deg"]}" end)} (strays {pair["step_error_deg"]["dec"]}°)
          </span>
          <span class="dim">The stray is the practical margin: it holds tracking noise and lens distortion the fit's own ± does not know about</span>
          <span :if={sw["history_spread_deg"]} class="dim">The last {sw["history_n"]} sweeps put the RA axis within <b>{sw["history_spread_deg"]}°</b> of each other: repeatability, the margin that counts</span>
        </div>

        <div :for={{axis, label} <- [{"ra", "RA axis"}, {"dec", "Dec axis"}]} class="axes-row">
          <% f = sw[axis]["fit"] %>
          <strong class={"ax-#{axis}"}>{label}</strong>
          <span :if={f}>
            Runs at <b>{f["image_angle_deg"]}° ± {margin(f["image_angle_sd_deg"], f["bootstrap_sd_deg"])}°</b> across the picture,
            <%= if f["tilt_ambiguous"] do %>
              tilt <b>about {abs(f["tilt_deg"])}°, toward or away the camera can't tell</b> from a sweep this small; the arcs are too nearly straight. Try the wide sweep.
            <% else %>
              tilted <b>{abs(f["tilt_deg"])}° ± {margin(f["tilt_sd_deg"], f["bootstrap_sd_deg"])}°</b> out of the picture
            <% end %>
          </span>
          <span :if={f} class="dim">{f["n"]} spots followed through {length(sw["angles"])} positions · arcs fit to {f["rms_px"]} px · depth is in units of the distance to the axis (one camera can't scale it)</span>
          <span :if={!f} class="dim">Not enough spots could be followed through the whole sweep</span>
        </div>
        <% ambiguous = sw["ra"]["fit"]["tilt_ambiguous"] == true or sw["dec"]["fit"]["tilt_ambiguous"] == true %>
        <div :if={sw["between_deg"] && !ambiguous} class="axes-row">
          <strong>Between the two axes</strong>
          <span><b>{sw["between_deg"]}°</b> · a square mount reads 90°; the difference is measurement error plus whatever the mount really is</span>
        </div>
        <div :if={sw["between_deg"] && ambiguous} class="axes-row">
          <strong>Between the two axes</strong>
          <span class="dim">Not known yet: with a tilt unresolved the angle between them could be anything from {Float.round(abs(sw["ra"]["fit"]["image_angle_deg"] - sw["dec"]["fit"]["image_angle_deg"]) / 1, 0)}° up; a wider sweep settles it</span>
        </div>
        <.hint>Margins are 1σ: the larger of the fit's own estimate and a bootstrap over which spots were used. Not included: the camera's field of view is assumed ({sw["hfov_deg"]}°, a setting) and lens distortion is ignored; both bias the tilt more than the in-picture direction.</.hint>
      </.card>

      <.card :if={@result && @result["ra"]} title={"Quick Look · #{String.slice(@result["at"], 11, 5)} UTC"}>
        <div class="axes-pic">
          <img :if={@result["frame"]} src={~p"/watch/frames/#{@result["frame"]}"} alt="the frame before any move" />
          <svg viewBox={"0 0 #{@result["w"]} #{@result["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <defs>
              <marker id="ah-ra" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="var(--accent)" /></marker>
              <marker id="ah-dec" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="none" stroke="var(--on)" stroke-width="1" /></marker>
            </defs>
            <%= for {axis, colour, dash} <- [{"ra", "var(--accent)", "10 8"}, {"dec", "var(--on)", "4 4"}] do %>
              <% ax = @result[axis] %>
              <line :for={v <- ax["vectors"]} x1={v["x"]} y1={v["y"]} x2={v["x"] + v["dx"] * 4} y2={v["y"] + v["dy"] * 4} stroke={colour} stroke-width="1.6" stroke-linecap="round" opacity="0.95" marker-end={"url(#ah-#{axis})"} />
              <%!-- the axis direction across the picture, when the motion is a slide --%>
              <line :if={ax["line"] && ax["fit"] && ax["fit"]["coherence"] > 0.5} x1={ax["line"]["x"] - ax["line"]["ux"] * 2000} y1={ax["line"]["y"] - ax["line"]["uy"] * 2000} x2={ax["line"]["x"] + ax["line"]["ux"] * 2000} y2={ax["line"]["y"] + ax["line"]["uy"] * 2000} stroke={colour} stroke-width="2" stroke-dasharray={dash} opacity="0.8" />
              <g :if={ax["fit"] && ax["fit"]["cx"]}>
                <circle cx={ax["fit"]["cx"]} cy={ax["fit"]["cy"]} r="9" fill="none" stroke={colour} stroke-width="2" />
                <line x1={ax["fit"]["cx"] - 16} y1={ax["fit"]["cy"]} x2={ax["fit"]["cx"] + 16} y2={ax["fit"]["cy"]} stroke={colour} stroke-width="1.6" />
                <line x1={ax["fit"]["cx"]} y1={ax["fit"]["cy"] - 16} x2={ax["fit"]["cx"]} y2={ax["fit"]["cy"] + 16} stroke={colour} stroke-width="1.6" />
              </g>
            <% end %>
          </svg>
        </div>
        <div :for={{axis, label} <- [{"ra", "RA axis"}, {"dec", "Dec axis"}]} class="axes-row">
          <% ax = @result[axis] %>
          <strong class={"ax-#{axis}"}>{label}</strong>
          <span>{ax["words"]}</span>
          <span :if={ax["fit"]} class="dim">
            {length(ax["vectors"])} blocks moved{if (ax["dropped"] || 0) > 0, do: " (#{ax["dropped"]} odd ones ignored)"} ·
            {if ax["fit"]["cx"], do: "pivot at (#{round(ax["fit"]["cx"] * @result["scale"])}, #{round(ax["fit"]["cy"] * @result["scale"])}) px · "}
            fit: turn {pct(ax["fit"]["quality"])}, slide {pct(ax["fit"]["coherence"])}
          </span>
          <span :if={!ax["fit"]} class="dim">Nothing moved enough to measure</span>
          <%!-- the line only means something for a slide; a turn has a pivot, not a direction --%>
          <span :if={ax["line"] && @predicted && ax["fit"] && ax["fit"]["coherence"] > 0.5} class="dim">
            Camera sees this axis at {round(measured(ax))}° · the orb, viewed from {@predicted["from"]}°, draws it at {round(@predicted[axis])}° · {apart(measured(ax), @predicted[axis])}° apart
          </span>
        </div>
        <.hint :if={@predicted}>The comparison with the orb only means something if the orb's viewpoint (Orb › From N/E/S/W, or Setup) is roughly where the camera stands; camera roll and height are not accounted for yet.</.hint>
        <.hint>Arrows show where the picture moved when that axis turned (RA with solid arrowheads, Dec with open ones), stretched 4×. A dashed line is the axis's direction across the picture when the motion is a slide (long dashes RA, short dashes Dec); a cross is the best-fit pivot when it turns. Numbers are in the original frame's pixels.</.hint>
      </.card>

      <% end %>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # settings come back from JSON: a whole number may be an integer by the time it is here
  defp margin(a, b) do
    [a, b, 0.5] |> Enum.reject(&is_nil/1) |> Enum.max() |> Kernel./(1) |> Float.round(1)
  end

  # The fit's projected segment can be short or off the picture (the axis point
  # sits at an arbitrary depth): draw the axis as a long line through the
  # segment's midpoint instead, falling back to the in-picture angle, and put
  # the label where the line meets the picture's edge region.
  defp long_line(%{"line" => [[x1, y1], [x2, y2]]} = f, w, h) do
    {mx, my} = {(x1 + x2) / 2, (y1 + y2) / 2}
    {dx, dy} = {x2 - x1, y2 - y1}
    len = :math.sqrt(dx * dx + dy * dy)

    {ux, uy} =
      if len > 2.0 do
        {dx / len, dy / len}
      else
        a = (f["image_angle_deg"] || 0.0) * :math.pi() / 180
        {:math.cos(a), :math.sin(a)}
      end

    {mx, my} = if mx < 0 or mx > w or my < 0 or my > h, do: {w / 2, h / 2}, else: {mx, my}
    reach = w + h
    lx = mx + ux * w * 0.3
    ly = my + uy * w * 0.3 - 8
    %{x1: mx - ux * reach, y1: my - uy * reach, x2: mx + ux * reach, y2: my + uy * reach, lx: min(max(lx, 8), w - 60), ly: min(max(ly, 20), h - 8)}
  end

  defp long_line(_, _, _), do: nil

  # what the running view says it is doing right now
  defp doing_words(%{step: {:sweep, ax, i, n}}), do: "Turning #{axis_name(ax)} to position #{i} of #{n}, then a still"
  defp doing_words(%{step: {:capture, ax}}), do: "Still after #{axis_name(ax)} moved"
  defp doing_words(%{step: {:move, ax}}), do: "Turning #{axis_name(ax)}"
  defp doing_words(%{step: :capture_before}), do: "First still, before anything moves"
  defp doing_words(%{step: :pair_fit}), do: "Fitting both axes together"
  defp doing_words(%{step: {:analyse, ax}}), do: "Working out the #{axis_name(ax)} axis from what moved"
  defp doing_words(%{step: :starting}), do: "Getting the camera"
  defp doing_words(_), do: "Working"

  defp axis_name(:ra), do: "RA"
  defp axis_name(:dec), do: "Dec"
  defp axis_name(other), do: to_string(other)

  defp positions_done(%{interim: im}, axis) when is_map(im), do: (im[axis] && im[axis]["positions"]) || (if axis == "ra" and im["dec"], do: 5, else: 0)
  defp positions_done(_, _), do: 0

  defp running_axis?(%{step: {:sweep, ax, _, _}}, axis), do: Atom.to_string(ax) == axis
  defp running_axis?(%{step: {:capture, ax}}, axis), do: Atom.to_string(ax) == axis
  defp running_axis?(%{step: {:move, ax}}, axis), do: Atom.to_string(ax) == axis
  defp running_axis?(_, _), do: false

  defp elapsed_words(nil), do: "Just started"

  defp elapsed_words(t0) do
    case div(System.monotonic_time(:second) - t0, 60) do
      0 -> "Under a minute in"
      1 -> "A minute in"
      m -> "#{m} min in"
    end
  end

  # one sentence per axis for the answer card; the numbers live in the details
  defp answer_across(%{"image_angle_deg" => a} = f, _), do: "runs at #{round1(a)}° across the picture#{sd(f["image_angle_sd_deg"])}"
  defp answer_across(_, %{"image_angle_deg" => a} = f), do: "runs at #{round1(a)}° across the picture#{sd(f["image_angle_sd_deg"])}"
  defp answer_across(_, _), do: "Not found in this run"

  defp answer_depth(%{"tilt_deg" => t} = f, _) when is_number(t), do: "#{round1(abs(t))}° in or out of the picture#{sd(f["tilt_sd_deg"])}"
  defp answer_depth(_, %{"tilt_ambiguous" => true, "tilt_deg" => t}), do: "About #{round1(abs(t))}° in or out; which way, this run can't tell"
  defp answer_depth(_, %{"tilt_deg" => t} = f) when is_number(t), do: "#{round1(abs(t))}° in or out of the picture#{sd(f["tilt_sd_deg"])}"
  defp answer_depth(_, _), do: "Not enough spots followed"

  defp confidence_words(%{"history_spread_deg" => spread, "history_n" => n}) when is_number(spread) and n >= 2 do
    cond do
      spread <= 2 -> "#{n} runs agree within #{round1(spread)}°: solid"
      spread <= 8 -> "#{n} runs agree within #{round1(spread)}°: usable, run it again to be sure"
      true -> "#{n} runs disagree by #{round1(spread)}°: not reliable yet. Moved the camera? Forget these results and start again"
    end
  end

  defp confidence_words(_), do: "One run so far: run it again to see if it repeats"

  # a 0..1 fit score as a percentage: how much the motion looks like a turn, or a slide
  defp pct(x) when is_number(x), do: "#{round(x * 100)}%"
  defp pct(_), do: Controller.Words.none()

  defp sd(nil), do: ""
  defp sd(x) when is_number(x), do: " (±#{round1(x)}°)"
  defp sd(_), do: ""
  defp round1(x) when is_number(x), do: Float.round(x / 1, 1)
  defp round1(x), do: x

  defp step_words(%{running: false, step: :done}), do: "Done"
  defp step_words(%{running: false, step: :failed}), do: "Failed"
  defp step_words(%{running: false, step: :cancelled}), do: "Cancelled"
  defp step_words(%{running: false}), do: "Idle"
  defp step_words(%{step: :capture_before}), do: "First still"
  defp step_words(%{step: {:move, ax}}), do: "Turning #{axis_name(ax)}"
  defp step_words(%{step: {:capture, ax}}), do: "Still after #{axis_name(ax)}"
  defp step_words(%{step: {:sweep, ax, i, n}}), do: "#{axis_name(ax)} · position #{i} of #{n}"
  defp step_words(%{step: :pair_fit}), do: "Fitting both axes together"
  defp step_words(%{step: {:analyse, ax}}), do: "Looking at #{axis_name(ax)}"
  defp step_words(_), do: "Working"
end
