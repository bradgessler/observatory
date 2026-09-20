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
     |> assign(page_title: "Optical Axes", night: Settings.get("night", false), nested: session["nested"] == true, selected: params["id"] || session["id"], mounts: [], notice: nil)
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

  def handle_info({:optical, status}, socket), do: {:noreply, socket |> assign(scan: status) |> load()}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "optical_axes", _}, socket), do: {:noreply, load(socket)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_event("run", _, socket) do
    case AxisScan.run(socket.assigns.selected) do
      :ok -> {:noreply, assign(socket, notice: "scanning: the mount will move ±3° on each axis")}
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
      nil -> {:noreply, assign(socket, notice: "that sweep range is not one on offer")}
      :ok -> {:noreply, assign(socket, notice: "sweeping: five positions per axis, ±#{round(half)}°, about three minutes")}
      {:error, why} -> {:noreply, assign(socket, notice: refused(why))}
    end
  end

  def handle_event("refine", _, socket) do
    case AxisScan.refine(socket.assigns.selected, range: 6.0) do
      :ok -> {:noreply, assign(socket, notice: "refining: a sweep every few minutes until you stop it")}
      {:error, why} -> {:noreply, assign(socket, notice: refused(why))}
    end
  end

  def handle_event("stop_refining", _, socket) do
    AxisScan.stop_refining()
    {:noreply, assign(socket, notice: "this run finishes, then it stops")}
  end

  def handle_event("cancel", _, socket) do
    AxisScan.cancel()
    {:noreply, assign(socket, notice: "cancelled; going back to where it started")}
  end

  def handle_event("clear", _, socket) do
    AxisScan.clear(socket.assigns.selected)
    {:noreply, load(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp refused(:busy), do: "a scan is already running"
  defp refused(:no_mount), do: "no mount to scan"
  defp refused(why) when is_binary(why), do: why
  defp refused(why), do: inspect(why)

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="axes" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/controls/watch"} label="Watch" />
        <.title>Optical Axes</.title>
        <.actions><.help href={~p"/docs/axes"} label="the optical axes" /></.actions>
      </:header>

      <%!-- the procedure: one key, a line that says what it is doing, and an answer --%>
      <.card title="Find the Axes">
        <:aside><span role="status" aria-live="polite"><.badge on={@scan.running} warn={@scan.step in [:failed, :cancelled]}>{step_words(@scan)}</.badge></span></:aside>
        <% cannot = @scan.running or is_nil(@selected) or is_nil(@camera.tool) or not @homed %>
        <.hint>Turns each axis a few degrees with the camera watching and works out where the two axes are in the picture. The mount comes back to where it started.</.hint>
        <div :if={@scan.running} class="state-line" role="status" aria-live="polite">
          <strong>{step_words(@scan)}</strong>
          <span class="dim">{if @scan[:loop], do: "refining: run after run until you stop it", else: "about ten minutes"} · STOP on any page ends it</span>
        </div>
        <.row :if={!@scan.running}>
          <.btn variant="primary" phx-click="sweep" phx-value-range="6.0" disabled={cannot}>Find the axes · 10 min</.btn>
          <.btn phx-click="refine" disabled={cannot}>Keep refining</.btn>
        </.row>
        <.row :if={@scan.running}>
          <.btn :if={@scan[:loop]} phx-click="stop_refining">Stop after this run</.btn>
          <.btn phx-click="cancel">Cancel and go back</.btn>
        </.row>
        <.row :if={!@scan.running}>
          <.btn class="btn-ghost" phx-click="run" disabled={cannot}>Quick look · 1 min</.btn>
          <.btn class="btn-ghost" phx-click="sweep" phx-value-range="20.0" disabled={cannot}>Wide sweep · 20 min</.btn>
        </.row>
        <.hint :if={is_nil(@camera.tool)}>No camera tool on this machine.</.hint>
        <.hint :if={@selected && !@homed}>Zero the axes first (<.link navigate={~p"/setup/#{@selected}"}>Setup</.link>): the soft limits that keep a scan safe are only armed once the mount knows where it is.</.hint>
        <.hint :if={@scan.error} class="err" role="alert">{@scan.error}</.hint>
      </.card>

      <%!-- while it runs: the fit on the positions so far, redrawn as each picture lands --%>
      <% im = @scan[:interim] || %{} %>
      <% first = im["ra"] || im["dec"] %>
      <.card :if={@scan.running && first && !@details} title="Emerging">
        <div class="axes-pic">
          <img src={~p"/watch/frames/#{first["frame"]}"} alt="the mount, with the axes found so far drawn over it" />
          <svg viewBox={"0 0 #{first["w"]} #{first["h"]}"} preserveAspectRatio="none" class="axes-overlay" aria-hidden="true">
            <%= for {axis, colour} <- [{"ra", "var(--accent)"}, {"dec", "var(--on)"}], im[axis] do %>
              <polyline :for={t <- im[axis]["tracks"] || []} points={Enum.map_join(t, " ", fn [x, y] -> "#{x},#{y}" end)} fill="none" stroke={colour} stroke-width="1.2" opacity="0.85" />
            <% end %>
            <%= for {axis, colour, dash, name} <- [{"ra", "var(--accent)", "12 8", "RA"}, {"dec", "var(--on)", "4 4", "Dec"}], f = im[axis] && im[axis]["fit"], f && f["line"] do %>
              <line x1={f["line"] |> hd() |> hd()} y1={f["line"] |> hd() |> Enum.at(1)} x2={f["line"] |> Enum.at(1) |> hd()} y2={f["line"] |> Enum.at(1) |> Enum.at(1)} stroke={colour} stroke-width="3" stroke-dasharray={dash} />
              <text x={f["line"] |> Enum.at(1) |> hd()} y={(f["line"] |> Enum.at(1) |> Enum.at(1)) - 8} fill={colour} font-size={div(first["w"], 28)} font-weight="700">{name}</text>
            <% end %>
          </svg>
        </div>
        <div :for={{axis, label} <- [{"ra", "RA (polar) axis"}, {"dec", "Dec axis"}]} class="state-line">
          <strong>{label} · {cond do im[axis] && im[axis]["fit"] -> answer_across(nil, im[axis]["fit"]); im[axis] -> "#{length(im[axis]["tracks"] || [])} spots on the move"; true -> "waiting for its turn" end}</strong>
          <span :if={im[axis]} class="dim">after {im[axis]["positions"]} of {im[axis]["of"]} positions{if im[axis]["fit"], do: " · #{im[axis]["fit"]["n"]} spots · arcs fit to #{im[axis]["fit"]["rms_px"]} px", else: " · a fit needs three"}</span>
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
              <% lf = pf || sw[axis]["fit"] %>
              <%= if lf && lf["line"] do %>
                <line x1={lf["line"] |> hd() |> hd()} y1={lf["line"] |> hd() |> Enum.at(1)} x2={lf["line"] |> Enum.at(1) |> hd()} y2={lf["line"] |> Enum.at(1) |> Enum.at(1)} stroke={colour} stroke-width="3" stroke-dasharray={dash} />
                <text x={lf["line"] |> Enum.at(1) |> hd()} y={(lf["line"] |> Enum.at(1) |> Enum.at(1)) - 8} fill={colour} font-size={div(sw["ra"]["w"], 28)} font-weight="700">{name}</text>
              <% end %>
            <% end %>
          </svg>
        </div>
        <div class="state-line">
          <strong>RA (polar) axis · {answer_across(pair && pair["polar"], sw["ra"]["fit"])}</strong>
          <span class="dim">{answer_depth(pair && pair["polar"], sw["ra"]["fit"])}</span>
        </div>
        <div class="state-line">
          <strong>Dec axis · {answer_across(pair && pair["dec"], sw["dec"]["fit"])}</strong>
          <span class="dim">{answer_depth(pair && pair["dec"], sw["dec"]["fit"])}</span>
        </div>
        <div class="state-line">
          <strong>{confidence_words(sw)}</strong>
          <span class="dim">the direction across the picture is the part one camera can measure; how far in or out needs a second camera</span>
        </div>
        <.row>
          <.btn :if={@selected} navigate={~p"/controls/watch"}>See them on the live picture ›</.btn>
          <.btn class="btn-ghost" patch={~p"/controls/watch/axes/#{@selected}?details=1"}>All the numbers ›</.btn>
        </.row>
      </.card>

      <.card :if={!sw && @result && @result["ra"] && !@details} title={"Quick Look · #{String.slice(@result["at"], 11, 5)} UTC"}>
        <div class="state-line">
          <strong>RA (polar) axis · {@result["ra"]["words"]}</strong>
        </div>
        <div class="state-line">
          <strong>Dec axis · {@result["dec"]["words"]}</strong>
        </div>
        <.hint>A quick look only says how each axis moves the picture. Find the axes for the lines.</.hint>
        <.row><.btn class="btn-ghost" patch={~p"/controls/watch/axes/#{@selected}?details=1"}>All the numbers ›</.btn></.row>
      </.card>

      <%= if @details do %>
      <.row>
        <.btn class="btn-ghost" patch={~p"/controls/watch/axes/#{@selected}"}>‹ Back to the answer</.btn>
        <.btn :if={@result} class="btn-ghost" phx-click="clear" data-confirm="Forget the axis scan results for this mount?">Forget these results</.btn>
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
            polar axis <b>{pair["polar"]["image_angle_deg"]}° ± {margin(pair["polar"]["image_angle_sd_deg"], nil)}°</b> across the picture, <b>{abs(pair["polar"]["tilt_deg"])}° ± {margin(pair["polar"]["tilt_sd_deg"], nil)}°</b> out of it ·
            Dec axis <b>{pair["dec"]["image_angle_deg"]}°</b> across, <b>{abs(pair["dec"]["tilt_deg"])}°</b> out · arcs fit to {pair["rms_px"]} px
          </span>
          <span class="dim">
            camera's reading of each commanded step · RA: {Enum.map_join(pair["steps"]["ra"], " · ", fn s -> "#{s["commanded_deg"]}→#{s["measured_deg"]}" end)} (strays {pair["step_error_deg"]["ra"]}°) ·
            Dec: {Enum.map_join(pair["steps"]["dec"], " · ", fn s -> "#{s["commanded_deg"]}→#{s["measured_deg"]}" end)} (strays {pair["step_error_deg"]["dec"]}°)
          </span>
          <span class="dim">the stray is the practical margin: it holds tracking noise and lens distortion the fit's own ± does not know about</span>
          <span :if={sw["history_spread_deg"]} class="dim">the last {sw["history_n"]} sweeps put the polar axis within <b>{sw["history_spread_deg"]}°</b> of each other: repeatability, the margin that counts</span>
        </div>

        <div :for={{axis, label} <- [{"ra", "RA · polar axis"}, {"dec", "Dec axis"}]} class="axes-row">
          <% f = sw[axis]["fit"] %>
          <strong class={"ax-#{axis}"}>{label}</strong>
          <span :if={f}>
            runs at <b>{f["image_angle_deg"]}° ± {margin(f["image_angle_sd_deg"], f["bootstrap_sd_deg"])}°</b> across the picture,
            <%= if f["tilt_ambiguous"] do %>
              tilt <b>about {abs(f["tilt_deg"])}°, toward or away the camera can't tell</b> from a sweep this small; the arcs are too nearly straight. Try the wide sweep.
            <% else %>
              tilted <b>{abs(f["tilt_deg"])}° ± {margin(f["tilt_sd_deg"], f["bootstrap_sd_deg"])}°</b> out of the picture
            <% end %>
          </span>
          <span :if={f} class="dim">{f["n"]} spots followed through {length(sw["angles"])} positions · arcs fit to {f["rms_px"]} px · depth is in units of the distance to the axis (one camera can't scale it)</span>
          <span :if={!f} class="dim">not enough spots could be followed through the whole sweep</span>
        </div>
        <% ambiguous = sw["ra"]["fit"]["tilt_ambiguous"] == true or sw["dec"]["fit"]["tilt_ambiguous"] == true %>
        <div :if={sw["between_deg"] && !ambiguous} class="axes-row">
          <strong>Between the two axes</strong>
          <span><b>{sw["between_deg"]}°</b> · a square mount reads 90°; the difference is measurement error plus whatever the mount really is</span>
        </div>
        <div :if={sw["between_deg"] && ambiguous} class="axes-row">
          <strong>Between the two axes</strong>
          <span class="dim">not known yet: with a tilt unresolved the angle between them could be anything from {Float.round(abs(sw["ra"]["fit"]["image_angle_deg"] - sw["dec"]["fit"]["image_angle_deg"]) / 1, 0)}° up; a wider sweep settles it</span>
        </div>
        <.hint>Margins are 1σ: the larger of the fit's own estimate and a bootstrap over which spots were used. Not included: the camera's field of view is assumed ({sw["hfov_deg"]}°, a setting) and lens distortion is ignored; both bias the tilt more than the in-picture direction.</.hint>
      </.card>

      <.card :if={@result && @result["ra"]} title={"Quick look · #{String.slice(@result["at"], 11, 5)} UTC"}>
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

  # one sentence per axis for the answer card; the numbers live in the details
  defp answer_across(%{"image_angle_deg" => a} = f, _), do: "runs at #{round1(a)}° across the picture#{sd(f["image_angle_sd_deg"])}"
  defp answer_across(_, %{"image_angle_deg" => a} = f), do: "runs at #{round1(a)}° across the picture#{sd(f["image_angle_sd_deg"])}"
  defp answer_across(_, _), do: "not found in this run"

  defp answer_depth(%{"tilt_deg" => t} = f, _) when is_number(t), do: "#{round1(abs(t))}° in or out of the picture#{sd(f["tilt_sd_deg"])}"
  defp answer_depth(_, %{"tilt_ambiguous" => true, "tilt_deg" => t}), do: "about #{round1(abs(t))}° in or out; which way, this run can't tell"
  defp answer_depth(_, %{"tilt_deg" => t} = f) when is_number(t), do: "#{round1(abs(t))}° in or out of the picture#{sd(f["tilt_sd_deg"])}"
  defp answer_depth(_, _), do: "not enough spots followed"

  defp confidence_words(%{"history_spread_deg" => spread, "history_n" => n}) when is_number(spread) and n >= 2 do
    cond do
      spread <= 2 -> "#{n} runs agree within #{round1(spread)}°: solid"
      spread <= 8 -> "#{n} runs agree within #{round1(spread)}°: usable, run it again to be sure"
      true -> "#{n} runs disagree by #{round1(spread)}°: not reliable yet, run it again"
    end
  end

  defp confidence_words(_), do: "one run so far: run it again to see if it repeats"

  defp sd(nil), do: ""
  defp sd(x) when is_number(x), do: " (±#{round1(x)}°)"
  defp sd(_), do: ""
  defp round1(x) when is_number(x), do: Float.round(x / 1, 1)
  defp round1(x), do: x

  defp step_words(%{running: false, step: :done}), do: "done"
  defp step_words(%{running: false, step: :failed}), do: "failed"
  defp step_words(%{running: false, step: :cancelled}), do: "cancelled"
  defp step_words(%{running: false}), do: "idle"
  defp step_words(%{step: :capture_before}), do: "first picture"
  defp step_words(%{step: {:move, ax}}), do: "turning #{ax}"
  defp step_words(%{step: {:capture, ax}}), do: "picture after #{ax}"
  defp step_words(%{step: {:sweep, ax, i, n}}), do: "#{ax} · position #{i} of #{n}"
  defp step_words(%{step: :pair_fit}), do: "fitting both axes together"
  defp step_words(%{step: {:analyse, ax}}), do: "looking at #{ax}"
  defp step_words(_), do: "working"
end
