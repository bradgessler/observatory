defmodule Controller.AlignPhotoLive do
  @moduledoc """
  Align by Photo: hold the phone to the eyepiece, take a picture, move on,
  take another. Each photo becomes a plate (`Controller.Plates`): the mount's
  encoders are read the moment the photo is chosen, the photo solves in the
  background, and every solved plate refits how the mount really sits. Two
  plates with the RA axis swung between them say which bolt to turn and how
  far; each after that firms it up. "Use This Alignment" hands them to Star
  Align so GoTo goes through them.

  One primary action, always ready: Take Photo, a LiveView upload with
  `capture="environment"` (iOS opens the camera straight away). The queue
  and the answer live in `Controller.Plates` and arrive here by broadcast,
  so every phone sees the same plates land.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Plates, Settings}
  alias Controller.Components.Counterweight
  alias Controller.Sky.{Lineup, Pointing, Polar, Solve, Tracker}

  @where_every_ms 30_000

  @impl true
  def mount(params, session, socket) do
    params = if is_map(params), do: params, else: %{}

    socket =
      socket
      |> assign(
        night: Settings.get("night", false),
        nested: session["nested"] == true,
        refs: %{},
        selected: params["id"] || session["id"] || session["telescope"],
        watching: nil,
        snap: nil,
        # the alignment in force for this mount, for the one question the photos cannot answer
        model: nil,
        notice: nil,
        # where solves would run: :checking until the cluster has been asked
        solver: :checking,
        plates_status: Plates.status(),
        # the capture for each photo chosen and still uploading, by entry ref
        captures: %{},
        now_ms: System.system_time(:millisecond),
        ticking: false
      )
      |> assign_view(nil)
      |> allow_upload(:photo,
        # "image/*" with capture: iOS opens the camera and hands over a JPEG
        accept: ~w(image/*),
        max_entries: 1,
        max_file_size: 40_000_000,
        auto_upload: true,
        progress: &handle_progress/3
      )

    if connected?(socket) do
      Settings.subscribe()
      send(self(), :rescan)
      send(self(), :where)
    end

    {:ok, rescan(socket)}
  end

  # -- live updates ---------------------------------------------------------------------

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  # asking other nodes can take a second or two: never on the page's own time
  def handle_info(:where, socket) do
    Process.send_after(self(), :where, @where_every_ms)
    {:noreply, start_async(socket, :solver, fn -> Solve.where() end)}
  end

  def handle_info(:tick, socket), do: {:noreply, socket |> assign(ticking: false) |> tick()}

  def handle_info({:plates, id, view}, socket) do
    if id == socket.assigns.selected, do: {:noreply, socket |> assign_view(view) |> tick()}, else: {:noreply, socket}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  # the alignment changed (Use This Alignment here, a Centered or an answer on another phone)
  def handle_info({:settings, "lineup", _}, socket), do: {:noreply, assign(socket, model: model(socket.assigns.selected))}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  @impl true
  def handle_async(:solver, {:ok, where}, socket), do: {:noreply, assign(socket, solver: where)}
  def handle_async(:solver, {:exit, _}, socket), do: {:noreply, assign(socket, solver: nil)}

  defp rescan(socket) do
    refs = Map.new(safe_list(), &{&1.id, &1})
    seen = socket.assigns[:subscribed] || MapSet.new()
    for {id, ref} <- refs, not MapSet.member?(seen, id), do: Mount.subscribe(ref)
    socket = assign(socket, subscribed: Enum.reduce(Map.keys(refs), seen, &MapSet.put(&2, &1)))
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    socket
    |> assign(refs: refs, selected: selected, snap: snap || socket.assigns.snap, model: model(selected), page_title: Controller.Words.title(selected, "Align by Photo"))
    |> watch(selected)
  end

  defp model(nil), do: nil
  defp model(id), do: Lineup.model(id)

  # follow the selected mount's plates; ask for them again when plate
  # solving comes back from having given up
  defp watch(socket, nil), do: assign(socket, plates_status: Plates.status())

  defp watch(socket, id) do
    status = Plates.status()
    was = socket.assigns.plates_status

    socket =
      if socket.assigns.watching != id and connected?(socket) do
        Plates.subscribe(id)
        assign(socket, watching: id)
      else
        socket
      end

    socket = assign(socket, plates_status: status)

    if socket.assigns.view == nil or socket.assigns.view.mount != id or (not is_map(was) and is_map(status)) do
      socket |> assign_view(fetch_view(id)) |> tick()
    else
      socket
    end
  end

  defp fetch_view(id) do
    case Plates.view(id) do
      %{} = view -> view
      _ -> nil
    end
  end

  defp assign_view(socket, view), do: assign(socket, view: view)

  # a one-second tick while anything is solving: for the elapsed seconds, and nothing else
  defp tick(socket) do
    solving = socket.assigns.view && Enum.any?(socket.assigns.view.plates, &(&1.state == :solving))

    socket = assign(socket, now_ms: System.system_time(:millisecond))

    if solving and not socket.assigns.ticking do
      Process.send_after(self(), :tick, 1_000)
      assign(socket, ticking: true)
    else
      socket
    end
  end

  # -- the photo ------------------------------------------------------------------------

  # The moment a photo is chosen is the moment its plate belongs to: the
  # encoders are read then (on the change event, or the first progress,
  # whichever comes first), not when the bytes finish arriving. The scope
  # can already be on its way to the next patch of sky.
  defp capture_new(socket) do
    report = socket.assigns.view && socket.assigns.view.report

    captures =
      Enum.reduce(socket.assigns.uploads.photo.entries, socket.assigns.captures, fn entry, acc ->
        Map.put_new_lazy(acc, entry.ref, fn -> Plates.capture(socket.assigns.snap, report: report) end)
      end)

    assign(socket, captures: captures)
  end

  defp handle_progress(:photo, entry, socket) do
    socket = capture_new(socket)

    if entry.done? do
      cap = socket.assigns.captures[entry.ref]
      image = consume_uploaded_entry(socket, entry, fn %{path: path} -> {:ok, File.read!(path)} end)
      socket = assign(socket, captures: Map.delete(socket.assigns.captures, entry.ref))

      case Plates.add(socket.assigns.selected, image, cap) do
        {:ok, _n} -> {:noreply, socket}
        {:error, reason} -> {:noreply, put_notice(socket, refusal(reason))}
      end
    else
      {:noreply, socket}
    end
  end

  defp refusal(:no_mount), do: "No mount"
  defp refusal(:not_homed), do: Controller.Words.error(:not_homed)
  defp refusal(:old_photo), do: "That photo was taken more than 5 minutes ago: take a new one"
  defp refusal(:unsupported_image), do: "JPEG only for now: set Camera, Formats to Most Compatible"
  defp refusal(:down), do: "Plate solving has stopped: restart it below"
  defp refusal(other), do: "Photo refused: #{Controller.Words.error(other)}"

  # -- events -----------------------------------------------------------------------------

  @impl true
  def handle_event("validate", _, socket), do: {:noreply, capture_new(socket)}
  def handle_event("noop", _, socket), do: {:noreply, socket}

  def handle_event("home", _, socket) do
    Tracker.stop(socket.assigns.selected)
    {:noreply, socket |> run(&Mount.set_home/1) |> put_notice("Home set")}
  end

  def handle_event("use", _, socket) do
    case Plates.use_alignment(socket.assigns.selected) do
      {:ok, _status} -> {:noreply, put_notice(socket, "Go To now goes through these photos")}
      {:error, :too_few} -> {:noreply, put_notice(socket, "Two solved photos first")}
      {:error, _} -> {:noreply, put_notice(socket, "Plate solving has stopped")}
    end
  end

  def handle_event("clear", _, socket) do
    Plates.clear(socket.assigns.selected)
    {:noreply, put_notice(socket, "Photos cleared")}
  end

  # Which side the counterweight is on: the one thing no photo can say, so it is asked here, where
  # a mount with no home gets its alignment. The answer is for the mount as it stands this moment.
  def handle_event("counterweight", %{"where" => where}, socket) when where in ["below", "above"] do
    where = String.to_existing_atom(where)
    said = Counterweight.words(Lineup.set_counterweight(socket.assigns.selected, socket.assigns.snap, where), where)
    {:noreply, socket |> assign(model: model(socket.assigns.selected)) |> put_notice(said)}
  end

  def handle_event(action, %{"i" => n}, socket) when action in ["retry", "remove"] do
    with {n, ""} <- Integer.parse(n) do
      if action == "retry", do: Plates.retry(socket.assigns.selected, n), else: Plates.remove(socket.assigns.selected, n)
    end

    {:noreply, socket}
  end

  def handle_event("restart_plates", _, socket) do
    case Plates.restart() do
      :ok -> {:noreply, socket |> assign(watching: nil) |> rescan() |> put_notice("Plate solving restarted")}
      {:error, e} -> {:noreply, put_notice(socket, "Could not restart: #{Controller.Words.error(e)}")}
    end
  end

  def handle_event("estop", _, socket) do
    Tracker.stop(socket.assigns.selected)
    {:noreply, socket |> run(&Mount.emergency_stop/1) |> put_notice("Stopped")}
  end

  defp put_notice(socket, text), do: assign(socket, notice: {text, System.unique_integer([:positive])})

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        put_notice(socket, "No mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> socket
            {:error, e} -> put_notice(socket, Controller.Words.error(e))
          end
        catch
          :exit, _ -> put_notice(socket, "Mount unreachable")
        end
    end
  end

  # -- render -----------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    plates = if assigns.view, do: assigns.view.plates, else: []

    assigns =
      assign(assigns,
        plates: Enum.reverse(plates),
        solved: Enum.filter(plates, &(&1.state == :solved and not &1.moving)),
        last: List.last(plates),
        waiting: Enum.count(plates, &(&1.state == :queued)),
        solving: Enum.count(plates, &(&1.state == :solving)),
        report: assigns.view && assigns.view.report,
        # the model is fitted off to the side (#112): say when it is a photo behind, or when the last fit was dropped
        fitting: assigns.view != nil and assigns.view[:fitting] == true,
        fit_notice: assigns.view && assigns.view[:fit_notice],
        in_use: assigns.view != nil and assigns.view.applied,
        down: assigns.plates_status in [:down, :not_started],
        uploading: List.first(assigns.uploads.photo.entries),
        stale: assigns.snap != nil and plates != [] and assigns.view.home_at != Map.get(assigns.snap, :homed_at)
      )

    ~H"""
    <.page id="align-photo" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Alignment", @selected)} />
        <.title>Align by Photo</.title>
        <%!-- the Alignment section's status: how well this telescope is aligned, the same as the sidebar's --%>
        <.status label="Alignment"><Controller.Components.AlignmentStatus.bar summary={(assigns[:alignments] || %{})[@selected]} /></.status>
        <.actions><.help href={~p"/docs/align-photo"} label="align by photo" /><.stop click="estop" /></.actions>
      </:header>

      <.card :if={is_nil(@snap)} title="No Mount">
        <.hint>No mount found: plug the EQDIR cable into this machine or a box.</.hint>
      </.card>

      <%!-- setting home is a shortcut, not a need: the photos fit where the axes' zeros are --%>
      <p :if={@snap && !@snap.homed} class="hint" role="status">
        Home not set, which is fine. Lock both clutches and move only with the keypad or game controller from here: the photos work out the rest.
      </p>

      <.card :if={@plates_status == :down} title="Plate Solving Stopped">
        <.hint role="status">It kept crashing, so it stopped. The mount and every other page are fine; the photos are kept.</.hint>
        <.btn variant="primary" phx-click="restart_plates">Restart Plate Solving</.btn>
      </.card>

      <.card :if={@plates_status == :not_started} title="Plate Solving Not Running">
        <.hint role="status">This server was updated without a restart, so the photo queue never started.</.hint>
        <.btn variant="primary" phx-click="restart_plates">Start Plate Solving</.btn>
      </.card>

      <.card :if={@snap && !@down} title="Take Photos">
        <div class="state-line" role="status" aria-live="polite">
          <strong>{headline(assigns)}</strong>
          <span>{guidance(assigns)}</span>
        </div>
        <form id="photo-form" phx-change="validate" phx-submit="noop">
          <label class={["btn", "btn-primary", "take-photo", !can_shoot?(assigns) && "off"]}>
            <.live_file_input upload={@uploads.photo} capture="environment" disabled={!can_shoot?(assigns)} />
            <span>{if @uploading, do: "Uploading #{@uploading.progress}%", else: "Take Photo"}</span>
          </label>
        </form>
        <.hint :for={err <- upload_errors(@uploads.photo) ++ Enum.flat_map(@uploads.photo.entries, &upload_errors(@uploads.photo, &1))} role="status">
          {upload_error_words(err)}
        </.hint>
        <.hint>Hold the telescope still until you tap Use Photo. Then move on: photos are plate solved in the background. <.link href={~p"/docs/glossary#plate-solve"}>What's plate solving?</.link></.hint>
        <.hint :if={@solver == nil}>No plate solver on this machine or the cluster. See ? to install one.</.hint>
        <.hint :if={@solver not in [nil, :checking]}>Solving on {Solve.where_words(@solver)}.</.hint>
      </.card>

      <.card :if={@report && @report[:moves]} title="Polar Axis">
        <div class="state-line">
          <strong>{deg(@report.error_deg)} from the pole</strong>
          <span>{noise_words(@report)}</span>
        </div>
        {polar_plot(assigns)}
        <.hint>Facing the pole: the cross is the pole, the dot is where the polar axis points, the dashed ring its margin.</.hint>
        <.items label="adjustments">
          <.item :for={m <- @report.moves} as="li" label={knob_name(m)} detail={move_words(m)} />
          <.item as="li" label="Drift" detail={"Up to #{arcmin(@report.drift_arcmin_per_min, 2)} a minute with plain sidereal tracking"} />
        </.items>
        <.hint :if={!@report.spread_ok?} role="status">
          The photos are {whole(@report.spread_deg)}° apart in RA. Swing {whole(Polar.min_spread_deg())}° or more for a firmer answer.
        </.hint>
        <.hint :if={@report.signs != Pointing.pointing()} role="status">
          The photos fit the RA axis turning the other way. Use This Alignment corrects the axis sign (Modes).
        </.hint>
        <.row>
          <.btn variant="primary" on={@in_use} phx-click="use">{if @in_use, do: "In Use ✓", else: "Use This Alignment"}</.btn>
          <.btn variant="ghost" phx-click="clear" data-confirm="Forget every photo and start over?">Start Over</.btn>
        </.row>
        <.hint>After turning a bolt, Start Over: these photos describe the mount as it was.</.hint>
      </.card>

      <%!-- once Go To goes through an alignment on a mount with no home: the side the photos cannot say --%>
      <Counterweight.card cw={Lineup.counterweight(@model, @snap)} />

      <.card :if={@plates != []} title="Photos">
        <:aside :if={@waiting + @solving > 0}>{queue_words(@waiting, @solving)}</:aside>
        <.hint :if={@stale} role="status">Home was set again since these photos. The next photo starts a new set.</.hint>
        <.hint :if={@fit_notice} role="status">{@fit_notice}</.hint>
        <.hint :if={@fitting and !@fit_notice} role="status">Fitting the model with the new photos. The last one is in use meanwhile.</.hint>
        <.items label="photos">
          <.item :for={p <- @plates} as="li" label={"Photo #{p.n}"} detail={plate_words(p, @report, @now_ms)}>
            <.btn :if={p.state == :failed and not p.moving} phx-click="retry" phx-value-i={p.n} aria-label={"Retry photo #{p.n}"}>Retry</.btn>
            <.btn variant="ghost" phx-click="remove" phx-value-i={p.n} aria-label={"Remove photo #{p.n}"}>✕</.btn>
          </.item>
        </.items>
        <.row :if={!(@report && @report[:moves])}>
          <.btn variant="ghost" phx-click="clear" data-confirm="Forget every photo and start over?">Start Over</.btn>
        </.row>
      </.card>

      <.notice :if={!@nested} notice={@notice} />
    </.page>
    """
  end

  # -- words ------------------------------------------------------------------------------

  defp can_shoot?(a), do: a.solver != nil and a.snap != nil and not a.down

  # the one strong line: where the set stands
  defp headline(%{uploading: %{} = e}), do: "Uploading, #{e.progress}%"
  defp headline(%{solved: [], last: nil}), do: "Point at any stars"
  defp headline(%{solved: s}) when length(s) < 2, do: "Swing the RA axis"
  defp headline(_), do: "Another photo firms it up"

  # the line under it: what to do next, live from the encoders
  defp guidance(%{solver: nil}), do: "No plate solver found"
  defp guidance(%{last: nil}), do: "Take a photo through the eyepiece. Stars anywhere will do."

  defp guidance(%{last: last, snap: %{axes: %{ra: %{degrees: ra}}}}) do
    swing = abs(ra - last.enc.ra_deg)
    goal = Polar.min_spread_deg()

    if swing >= goal,
      do: "RA is #{whole(swing)}° from photo #{last.n}: take the next one",
      else: "RA is #{whole(swing)}° from photo #{last.n}: swing #{whole(goal)}° or more, then take the next one"
  end

  defp guidance(_), do: ""

  defp queue_words(0, s), do: "#{s} solving"
  defp queue_words(w, 0), do: "#{w} waiting"
  defp queue_words(w, s), do: "#{w} waiting, #{s} solving"

  defp plate_words(%{state: :queued, ahead: 0}, _, _), do: "Waiting, next"
  defp plate_words(%{state: :queued, ahead: n}, _, _) when is_integer(n), do: "Waiting, #{n} ahead"
  defp plate_words(%{state: :queued}, _, _), do: "Waiting"
  defp plate_words(%{state: :solving} = p, _, now), do: "Solving, #{max(div(now - (p.started_ms || now), 1000), 0)} s"
  defp plate_words(%{state: :failed, reason: r}, _, _), do: failure_words(r)

  defp plate_words(%{state: :solved, solution: s} = p, report, _now) do
    off = if report && report.n >= 3 && p.residual_arcmin, do: ", off by #{arcmin(p.residual_arcmin, 1)}", else: ""
    "RA #{hm(s.ra_deg)}, Dec #{dm(s.dec_deg)}, #{field(s[:width_deg])} field" <> off
  end

  defp failure_words("too_few_stars"), do: "Too few stars (needs about 15)"
  defp failure_words("no_solution"), do: "Stars, but no match: try another patch of sky"
  defp failure_words("below_horizon"), do: "A match below the horizon, so a false one: take it again"
  defp failure_words("moving"), do: "Telescope was moving: take it again"
  defp failure_words("timeout"), do: "Took too long to solve"
  defp failure_words("no_solver"), do: "No plate solver found"
  defp failure_words("unsupported_image"), do: "Can't read that photo: JPEG only for now"
  defp failure_words("crashed"), do: "The solver failed on this one"
  defp failure_words(other), do: "Solve failed: #{other |> to_string() |> String.replace("_", " ")}"

  defp upload_error_words(:too_large), do: "That photo is over 40 MB"
  defp upload_error_words(:not_accepted), do: "That file is not a photo"
  defp upload_error_words(:too_many_files), do: "One photo at a time"
  defp upload_error_words(other), do: "Upload failed: #{other |> to_string() |> String.replace("_", " ")}"

  defp knob_name(%{knob: :altitude}), do: "Altitude"
  defp knob_name(%{knob: :azimuth}), do: "Azimuth"

  # "Raise 0.5°, ±0.2°" / "Turn 0.8° west, ±0.3°"
  defp move_words(%{knob: :altitude, dir: dir, deg: d, margin_deg: m}), do: "#{if dir == :raise, do: "Raise", else: "Lower"} #{deg(d)}#{margin(m)}"
  defp move_words(%{knob: :azimuth, dir: dir, deg: d, margin_deg: m}), do: "Turn #{deg(d)} #{dir}#{margin(m)}"

  defp margin(nil), do: ", can't tell yet"
  defp margin(m), do: ", ±#{deg(m)}"

  defp noise_words(%{n: n, noise_from: :photos, sigma_arcmin: s}), do: "#{n} photos, which disagree by #{arcmin(s, 1)}: remove the worst"
  defp noise_words(%{n: 2}), do: "2 photos fit exactly; a third checks them"
  defp noise_words(%{n: n, rms_arcmin: rms}), do: "#{n} photos agree to #{arcmin(rms, 1)}"

  # -- the picture ---------------------------------------------------------------------------

  # The pole at the centre, the axis as a dot where it points (as seen facing
  # the pole: up is higher, east to the right in the north), its margin as a
  # dashed ellipse, a ring at a round number of degrees for scale.
  defp polar_plot(assigns) do
    r = assigns.report
    [alt_m, az_m] = r.moves
    east_sign = if Pointing.site().lat >= 0, do: 1, else: -1
    # the azimuth offset as an angle on the sky, beside the altitude one
    cos_alt = :math.cos(r.pole.alt * :math.pi() / 180)
    x = r.east_error_deg * cos_alt * east_sign
    y = r.alt_error_deg
    mx = (az_m.margin_deg || 0.0) * cos_alt
    my = alt_m.margin_deg || 0.0
    reach = Enum.max([abs(x) + mx, abs(y) + my, 0.1])
    ring = Enum.find([0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 45.0, 90.0], 90.0, &(&1 >= reach * 0.6))
    k = 64 / max(reach, ring)

    assigns =
      assign(assigns,
        px: 80 + x * k,
        py: 80 - y * k,
        rx: max(mx * k, 1.5),
        ry: max(my * k, 1.5),
        ring_r: ring * k,
        ring_label: deg(ring),
        east: if(east_sign == 1, do: "E", else: "W"),
        label: "Polar axis #{deg(r.error_deg)} from the pole: #{Enum.map_join(r.moves, ", ", &move_words/1)}"
      )

    ~H"""
    <svg class="polar-plot" viewBox="0 0 160 160" role="img" aria-label={@label}>
      <circle class="ring" cx="80" cy="80" r={@ring_r} />
      <text x={80 + @ring_r * 0.72} y={80 - @ring_r * 0.72 - 4}>{@ring_label}</text>
      <path class="pole" d="M72 80h16M80 72v16" />
      <ellipse class="margin" cx={@px} cy={@py} rx={@rx} ry={@ry} />
      <circle class="axis-dot" cx={@px} cy={@py} r="4" />
      <text x="80" y="10" text-anchor="middle">Up</text>
      <text x="154" y="84" text-anchor="end">{@east}</text>
    </svg>
    """
  end

  # -- numbers -------------------------------------------------------------------------------

  # a tenth of a degree is about what a bolt can be turned by; finer only when that is all there is
  defp deg(x) when x < 0.1, do: "#{:erlang.float_to_binary(x / 1, decimals: 2)}°"
  defp deg(x), do: "#{:erlang.float_to_binary(x / 1, decimals: 1)}°"
  defp arcmin(x, decimals), do: "#{:erlang.float_to_binary(x / 1, decimals: decimals)}′"
  defp whole(x), do: x |> round() |> Integer.to_string()

  defp hm(ra) do
    total = round(ra / 15 * 60)
    "#{pad(div(total, 60) |> rem(24))}h#{pad(rem(total, 60))}m"
  end

  defp dm(dec) do
    total = round(abs(dec) * 60)
    "#{if dec < 0, do: "-", else: ""}#{div(total, 60)}°#{pad(rem(total, 60))}′"
  end

  defp field(nil), do: "unknown"
  defp field(w) when w < 2, do: "#{round(w * 60)}′"
  defp field(w), do: "#{:erlang.float_to_binary(w / 1, decimals: 1)}°"

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp safe_list do
    Mount.list()
  catch
    :exit, _ -> []
  end
end
