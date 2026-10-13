defmodule Controller.AlignCameraLive do
  @moduledoc """
  Align with the Camera, step by step: the camera on the telescope takes a
  few pictures of the sky, each is plate solved on the box, and the ones
  that agree become the alignment. No star names and no eye at the eyepiece.

  The night this page was written for (12 October 2026) the same run sat as
  one card inside the Alignment page's Stars step. Brad could not find it,
  could not tell what it was doing, and afterwards did not know whether it
  had worked: it had not, and nothing said so. So it has a page of its own,
  listed under Alignment, with one thing to do on each step:

    1. **Camera**: is there one, and what does it see? Its latest picture and
       how long ago it was taken, and a key for a test picture.
    2. **Pictures**: one key starts it. Every picture is a row that says
       where it is: taken, finding stars, matching (hinted or against the
       whole sky) with the time it has used of the time it has, solved, or
       why not. The numbers are the plate queue's own (`Plates.view/1`'s
       `solving:`), not a counter with nothing behind it.
    3. **Counterweight**: the one question no picture can answer, only on a
       mount whose home was never set.
    4. **Look**: aligned, how well, and where to go next. Or not aligned, and
       why, in words.

  Nothing here is held in the browser: the run is `Controller.AutoAlign`'s,
  the pictures `Controller.Plates`', the camera `Controller.StillCamera`'s.
  Two phones on this page see the same step.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{AutoAlign, Plates, Settings, StillCamera}
  alias Controller.Components.{Counterweight, Pictures}
  alias Controller.Sky.{Lineup, Tracker}

  # the finder exposure a run sets the camera to (`AutoAlign`): a test picture uses the same
  @iso 6400
  @shutter "2"

  @impl true
  def mount(params, session, socket) do
    params = if is_map(params), do: params, else: %{}

    socket =
      assign(socket,
        night: Settings.get("night", false),
        refs: %{},
        selected: params["id"] || session["id"] || session["telescope"],
        watching: nil,
        snap: nil,
        run: nil,
        view: nil,
        still: still(),
        lineup: nil,
        model: nil,
        notice: nil,
        now_ms: System.system_time(:millisecond)
      )

    if connected?(socket) do
      Settings.subscribe()
      AutoAlign.subscribe()
      StillCamera.subscribe()
      send(self(), :rescan)
      Process.send_after(self(), :tick, 1_000)
    end

    {:ok, rescan(socket)}
  end

  # -- live updates ---------------------------------------------------------------------

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  # a clock for "taken 14 s ago" and for a solve's time used: once a second, nothing else
  def handle_info(:tick, socket) do
    Process.send_after(self(), :tick, 1_000)
    {:noreply, assign(socket, now_ms: System.system_time(:millisecond))}
  end

  def handle_info({:auto_align, id, run}, socket) do
    if id == socket.assigns.selected, do: {:noreply, socket |> assign(run: run) |> aligned()}, else: {:noreply, socket}
  end

  def handle_info({:plates, id, view}, socket) do
    # with the clock: a solve's time used is read against it
    if id == socket.assigns.selected, do: {:noreply, assign(socket, view: view, now_ms: System.system_time(:millisecond))}, else: {:noreply, socket}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  # another machine's simulated camera is not this telescope's
  def handle_info({:still_camera, st}, socket) do
    if StillCamera.listed?(st), do: {:noreply, assign(socket, still: st)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "lineup", _}, socket), do: {:noreply, aligned(socket)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}
  def handle_info(_, socket), do: {:noreply, socket}

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

    socket =
      if selected && socket.assigns.watching != selected && connected?(socket) do
        Plates.subscribe(selected)
        assign(socket, watching: selected)
      else
        socket
      end

    socket
    |> assign(
      refs: refs,
      selected: selected,
      snap: snap || socket.assigns.snap,
      run: selected && AutoAlign.status(selected),
      view: selected && safe(fn -> Plates.view(selected) end),
      still: still(),
      page_title: Controller.Words.title(selected, "Align with the Camera")
    )
    |> aligned()
  end

  # the alignment in force, and the model the counterweight question hangs on
  defp aligned(socket) do
    id = socket.assigns.selected
    assign(socket,
      lineup: id && safe(fn -> Lineup.status(id) end),
      model: id && safe(fn -> Lineup.model(id) end),
      # the alignment this run (or a reset) replaced, while it can still be brought back
      was: id && safe(fn -> Lineup.restorable(id) end)
    )
  end

  defp still do
    case safe(fn -> StillCamera.status() end) do
      %{} = st -> if StillCamera.listed?(st), do: st, else: nil
      _ -> nil
    end
  end

  defp safe_list do
    Mount.list()
  catch
    :exit, _ -> []
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end

  # -- events ---------------------------------------------------------------------------

  @impl true
  def handle_event("start", _, socket) do
    id = socket.assigns.selected

    case id && AutoAlign.start(id, overhead: at_pole?(socket.assigns.snap)) do
      :ok -> {:noreply, assign(socket, run: AutoAlign.status(id))}
      {:error, :running} -> {:noreply, socket}
      {:error, :no_camera} -> {:noreply, put_notice(socket, "No camera on the telescope")}
      {:error, :no_mount} -> {:noreply, put_notice(socket, "No mount")}
      {:error, e} -> {:noreply, put_notice(socket, Controller.Words.error(e))}
      nil -> {:noreply, put_notice(socket, "No mount")}
    end
  end

  def handle_event("carry_on", _, socket) do
    id = socket.assigns.selected

    case id && AutoAlign.start(id, keep: true) do
      :ok -> {:noreply, assign(socket, run: AutoAlign.status(id))}
      {:error, :running} -> {:noreply, socket}
      {:error, e} -> {:noreply, put_notice(socket, Controller.Words.error(e))}
      nil -> {:noreply, put_notice(socket, "No mount")}
    end
  end

  def handle_event("continue", _, socket) do
    AutoAlign.continue(socket.assigns.selected)
    {:noreply, socket}
  end

  def handle_event("stop_aligning", _, socket) do
    AutoAlign.stop(socket.assigns.selected)
    {:noreply, socket}
  end

  # One picture at the exposure a run uses, to see what the camera sees before starting. Off the
  # page's own time: turning the camera's dials takes seconds each.
  def handle_event("test_picture", _, socket) do
    case socket.assigns.still do
      %{camera: %{state: :ready, settings: now}} ->
        Task.Supervisor.start_child(Controller.ScopeCamera.Tasks, fn ->
          unless finder_exposure?(now), do: safe(fn -> StillCamera.set(iso: @iso, shutter: @shutter) end)
          StillCamera.shoot()
        end)

        {:noreply, put_notice(socket, "Taking a picture")}

      _ ->
        {:noreply, put_notice(socket, "No camera on the telescope")}
    end
  end

  # not under a run: its next picture would replace what was just brought back
  def handle_event("restore_alignment", _, socket) do
    if match?(%{done: false}, socket.assigns.run),
      do: {:noreply, put_notice(socket, "Stop aligning first")},
      else: {:noreply, socket |> put_notice(Controller.Components.AlignmentStatus.restore(socket.assigns.selected)) |> aligned()}
  end

  def handle_event("counterweight", %{"where" => where}, socket) when where in ["below", "above", "unknown"] do
    {_told?, said} = Counterweight.answer(socket.assigns.selected, socket.assigns.snap, where)
    {:noreply, socket |> aligned() |> put_notice(said)}
  end

  def handle_event("estop", _, socket) do
    id = socket.assigns.selected
    Tracker.stop(id)

    socket =
      case socket.assigns.refs[id] do
        nil -> put_notice(socket, "No mount")
        ref -> (safe(fn -> Mount.emergency_stop(ref) end) && put_notice(socket, "Stopped")) || put_notice(socket, "Mount unreachable")
      end

    {:noreply, socket}
  end

  defp put_notice(socket, text), do: assign(socket, notice: {text, System.unique_integer([:positive])})

  # straight after Set Home the tube lies along the polar axis, where turning RA only spins the view
  defp at_pole?(%{homed: true, axes: %{dec: %{degrees: d}}}) when is_number(d), do: abs(d) < 10
  defp at_pole?(_), do: false

  defp finder_exposure?(%{iso: @iso, shutter_s: s}) when is_number(s), do: abs(s - 2.0) < 0.01
  defp finder_exposure?(_), do: false

  # -- the page -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    cam = assigns.still && assigns.still.camera
    ready = match?(%{state: :ready}, cam)
    run = assigns.run
    running = match?(%{done: false}, run)
    lineup = assigns.lineup
    aligned = is_map(lineup) and lineup.n >= 3
    cw = Counterweight.asking(assigns.model, assigns.snap)
    plates = if assigns.view, do: assigns.view.plates, else: []

    step =
      cond do
        is_nil(assigns.snap) -> :camera
        running -> :pictures
        aligned and cw != nil -> :counterweight
        aligned -> :look
        true -> :camera
      end

    assigns =
      assign(assigns,
        cam: cam,
        ready: ready,
        running: running,
        aligned: aligned,
        cw: cw,
        step: step,
        # the pictures of this run, newest first; none shown before a run on a mount that has old ones
        pictures: if(run, do: Enum.reverse(plates), else: []),
        placed: Enum.count(plates, &(&1.state == :solved and &1[:moving] != true)),
        last: assigns.still && assigns.still.last,
        # a run that ended short of an alignment with solved pictures still in the queue
        resumable: is_map(run) and run[:done] == true and run[:ok] != true and not aligned and Enum.any?(plates, &(&1.state == :solved and &1[:moving] != true)),
        # the host of the machine this mount is on, when it is not this one ("observatory.local")
        elsewhere: (n = AutoAlign.elsewhere(assigns.selected)) && n |> Atom.to_string() |> String.split("@") |> List.last(),
        # a mount with home set has nothing resting on the counterweight question
        asks_side: assigns.snap != nil and assigns.snap[:homed] != true
      )

    ~H"""
    <%!-- a flow: one readable column on a wide screen, what this step is about first --%>
    <.page id="align-camera" night={@night} class="flow">
      <:header>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Alignment", @selected)} />
        <.title>Camera</.title>
        <.actions><.help href={~p"/docs/align-camera"} label="align with the camera" /><.stop click="estop" /></.actions>
      </:header>

      <%!-- one line on any phone: every step is its number, and the one you are on is spelled out --%>
      <ol class="flow-steps flow-now" aria-label="steps to align with the camera">
        <li :for={{key, label} <- steps(@asks_side)} class={step_state(key, @step, @asks_side)} aria-current={if key == @step, do: "step"}>
          <span class="flow-label">{label}</span><span :if={step_state(key, @step, @asks_side) == "done"} role="img" aria-label="done">✓</span>
        </li>
      </ol>

      <%!-- nothing is thrown away by aligning again: the alignment it replaced, and the key that brings it back --%>
      <Controller.Components.AlignmentStatus.set_aside :if={@step != :pictures} was={@was} />

      <%!-- a telescope on another machine: its camera and its alignment live there, so this page is that machine's --%>
      <.card :if={@elsewhere} title="On Another Machine">
        <div class="state-line">
          <strong>{@selected} is on {@elsewhere}</strong>
          <span>Its camera and its alignment are on that machine. The camera listed here is this machine's.</span>
        </div>
        <.row><.btn variant="primary" href={"http://#{@elsewhere}/align/camera"}>Open It on {@elsewhere} ›</.btn></.row>
      </.card>

      <.card :if={is_nil(@snap)} title="No Mount">
        <.hint role="status">No mount found: plug the EQDIR cable into this machine or a box.</.hint>
        <.row><.btn navigate={~p"/devices"}>Devices ›</.btn></.row>
      </.card>

      <%!-- step 1: is there a camera, and what does it see --%>
      <.card :if={@snap && @step == :camera && !@elsewhere} title="Camera">
        <div class="state-line">
          <strong>{camera_headline(@cam)}</strong>
          <span>{camera_detail(@cam)}</span>
        </div>
        <%!-- its last picture when it has one; no empty frame when it has none --%>
        <Pictures.latest :if={@ready && @last && @last[:w]} last={@last} now_ms={@now_ms} busy={@still.busy} shot={@still[:shot]} />
        <%!-- the last run's answer, when it did not get there --%>
        <p :if={@run && @run.done && !@run.ok} class="find-line tone-caution" role="status">Not aligned: {@run.words}.</p>
        <.hint :if={@ready}>Lens cap off, pointed at open sky, roughly in focus. It takes at least four pictures, with the telescope moving a little between them. About a minute a picture: four minutes or so.</.hint>
        <%!-- a run that was stopped keeps what it solved: carry on from there, or take all of them again --%>
        <.hint :if={@resumable} role="status">{@placed} of {@run.enough} pictures are solved and kept. Continue takes the rest from where the telescope stands.</.hint>
        <.row :if={@resumable}>
          <.btn variant="primary" phx-click="carry_on" disabled={!@ready}>Continue</.btn>
          <.btn phx-click="start" disabled={!@ready}>Start Over</.btn>
        </.row>
        <.row :if={!@resumable}>
          <.btn variant="primary" phx-click="start" disabled={!@ready}>{if @run && @run.done, do: "Start Again", else: "Start Aligning"}</.btn>
          <.btn phx-click="test_picture" disabled={!@ready or @still.busy}>{if @ready && @still.busy, do: "Taking…", else: "Test Picture"}</.btn>
        </.row>
        <.hint :if={!@ready}>No camera on the telescope? <.link navigate={~p"/align/photo/#{@selected}"}>Use a phone at the eyepiece ›</.link> or <.link navigate={~p"/controls/align/#{@selected}"}>centre stars by eye ›</.link></.hint>
      </.card>

      <%!-- step 2: the run. Top to bottom: the picture, what it is doing now, the one key, then a row
            for every picture. Only the rows grow, and they are last, so the key never moves under a thumb. --%>
      <.card :if={@step == :pictures} title="Pictures" class="align-run">
        <:aside>{@placed} of {@run.enough} solved</:aside>
        <Pictures.latest last={@last} now_ms={@now_ms} busy={@still && @still.busy} shot={@still && @still[:shot]} empty="The first picture is on its way" />
        <p class="align-now" role="status" aria-live="polite">{@run.words}</p>
        <.row>
          <.btn :if={@run.phase == :waiting} variant="primary" phx-click="continue">Continue</.btn>
          <.btn phx-click="stop_aligning">Stop Aligning</.btn>
        </.row>
        <Pictures.solves :if={@pictures != []} plates={@pictures} now_ms={@now_ms} />
        <.hint :if={@view && @view[:fit_notice]} role="status">{@view.fit_notice}</.hint>
      </.card>

      <%!-- step 3: the one thing no picture can say --%>
      <Counterweight.card :if={@step == :counterweight} cw={@cw} />

      <%!-- step 4: aligned --%>
      <.card :if={@step in [:counterweight, :look]} title={if @step == :look, do: "Look", else: "Aligned"}>
        <div class="state-line" role="status">
          <strong><span aria-hidden="true">✓ </span>Aligned: {@lineup.n} points agree{agree_words(@lineup)}</strong>
          <span>{@lineup[:axis_words] || "Go To and tracking use this now."}</span>
        </div>
        <.hint :if={@step == :counterweight} role="status">One more thing above: say where the counterweight is. Go To waits for it.</.hint>
        <.row :if={@step == :look}>
          <.btn variant="primary" navigate={~p"/tonight/#{@selected}"}>Tonight's List ›</.btn>
          <.btn phx-click="start" disabled={!@ready}>Align Again</.btn>
        </.row>
      </.card>

      <%!-- aligned and answered: what the counterweight was told stays here, under the result, to change --%>
      <Counterweight.card :if={@step == :look} cw={Lineup.counterweight(@model, @snap)} />

      <%!-- after the run: every picture it took, newest first, and how each solve ended --%>
      <.card :if={@pictures != [] and @step != :pictures} title="Plate Solving">
        <:aside :if={@view && @view[:fitting]}>fitting</:aside>
        <Pictures.solves plates={@pictures} now_ms={@now_ms} />
        <.hint :if={@view && @view[:fit_notice]} role="status">{@view.fit_notice}</.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp steps(true), do: [camera: "Camera", pictures: "Pictures", counterweight: "Counterweight", look: "Look"]
  defp steps(false), do: [camera: "Camera", pictures: "Pictures", look: "Look"]

  @order [:camera, :pictures, :counterweight, :look]
  defp step_state(key, step, _asks) do
    i = Enum.find_index(@order, &(&1 == key))
    j = Enum.find_index(@order, &(&1 == step))

    cond do
      i < j -> "done"
      i == j -> "now"
      true -> ""
    end
  end

  defp camera_headline(%{state: :ready} = cam), do: "#{camera_name(cam)}: ready"
  defp camera_headline(%{} = cam), do: "#{camera_name(cam)}: not ready"
  defp camera_headline(_), do: "No camera on the telescope"

  defp camera_detail(%{state: :ready, settings: %{} = s}) do
    [s[:iso] && "ISO #{s.iso}", s[:shutter] && "#{s.shutter} s", s[:battery] && "battery #{s.battery}%"] |> Enum.filter(& &1) |> Enum.join(" · ")
  end

  defp camera_detail(%{}), do: "Switch it on, USB to the box, set to PC Remote."
  defp camera_detail(_), do: "Put the camera on the telescope, USB to the box, switched on and set to PC Remote."

  defp camera_name(cam), do: cam[:name] || cam[:model] || "Camera"

  defp agree_words(%{rms_arcmin: rms}) when is_number(rms), do: " to #{Float.round(rms / 1, 1)}′"
  defp agree_words(_), do: ""
end
