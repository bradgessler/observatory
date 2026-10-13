defmodule Controller.StillCameraLive do
  @moduledoc """
  The camera on the telescope when it is a stills camera (a Sony a6000 in PC
  Remote): the same page a video camera gets, with frames that come seconds
  or minutes apart. So the latest picture is always on it, with how long ago
  it was taken.

  One job a screen:

    * `/cameras/stills`: the latest picture, a picture now or one after another, the star size to focus by
    * `/cameras/stills/exposure`: ISO and shutter speed
    * `/cameras/stills/lock`: Lock On, both motors steered from these pictures to hold the target still
    * `/cameras/stills/solving`: plate solving, and where each picture's solve stands

  Telescope Camera (`/cameras/telescope`) sends people here when this is the
  camera on the telescope. The camera is the server's
  (`Controller.StillCamera`); every phone sees the same pictures and the same lock.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{LockOn, Plates, Settings, StillCamera}
  alias Controller.Components.Pictures

  @isos [
    {"Auto", :auto},
    {"100", 100},
    {"400", 400},
    {"800", 800},
    {"1600", 1600},
    {"3200", 3200},
    {"6400", 6400}
  ]
  @shutters ~w(1/1000 1/250 1/60 1/15 1/4 1 4 15 30)

  @impl true
  def mount(params, session, socket) do
    mounts = safe(fn -> Mount.list() end) || []
    selected = params["id"] || session["telescope"] || Mount.default(Enum.map(mounts, & &1.id))

    if connected?(socket) do
      StillCamera.subscribe()
      LockOn.subscribe()
      Settings.subscribe()
      if selected, do: Plates.subscribe(selected)
      # the picture's age, and a solve's seconds
      Process.send_after(self(), :tick, 1_000)
    end

    {:ok,
     assign(socket,
       night: Settings.get("night", false),
       # the camera on the telescope, whichever machine of the cluster it is plugged into
       cam: StillCamera.find(),
       lock: LockOn.status(),
       selected: selected,
       plates: plates(selected),
       now_ms: System.system_time(:millisecond),
       notice: nil,
       turning: false
     )}
  end

  @impl true
  def handle_params(_params, _uri, socket), do: {:noreply, assign(socket, page_title: screen_title(socket.assigns.live_action))}

  defp screen_title(:exposure), do: "Exposure"
  defp screen_title(:lock), do: "Lock On"
  defp screen_title(:solving), do: "Plate Solving"
  defp screen_title(_), do: "Telescope Camera"

  # the solver's queue for this mount, newest first
  defp plates(nil), do: []
  defp plates(id), do: Enum.reverse((safe(fn -> Plates.view(id) end) || %{})[:plates] || [])

  # another machine's simulated camera is never this page's camera (StillCamera.listed?/2)
  @impl true
  def handle_info({:still_camera, cam}, socket), do: {:noreply, assign(socket, cam: StillCamera.prefer(socket.assigns.cam, cam))}

  def handle_info({:lock_on, lock}, socket), do: {:noreply, assign(socket, lock: lock)}

  def handle_info(:tick, socket) do
    Process.send_after(self(), :tick, 1_000)
    {:noreply, assign(socket, now_ms: System.system_time(:millisecond))}
  end

  def handle_info({:plates, id, view}, socket) do
    if id == socket.assigns.selected,
      do: {:noreply, assign(socket, plates: Enum.reverse(view[:plates] || []), now_ms: System.system_time(:millisecond))},
      else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}

  def handle_info({:set_done, result}, socket) do
    notice =
      if match?({:error, _}, result),
        do: "The camera didn't take the setting: #{inspect(elem(result, 1))}"

    {:noreply, assign(socket, turning: false, notice: notice)}
  end

  def handle_info(_, socket), do: {:noreply, socket}

  # -- events -------------------------------------------------------------------------------

  @impl true
  # every key goes to the machine the camera is on
  def handle_event("shoot", _, socket) do
    StillCamera.shoot(on: socket.assigns.cam[:node])
    {:noreply, socket}
  end

  def handle_event("continuous", %{"on" => on}, socket) do
    safe(fn -> StillCamera.continuous(on == "true", 0, on: socket.assigns.cam[:node]) end)
    {:noreply, socket}
  end

  # the dials turn a notch at a time: the page stays live while they do
  def handle_event("iso", %{"iso" => v}, socket), do: {:noreply, turn(socket, iso: parse_iso(v))}
  def handle_event("shutter", %{"shutter" => v}, socket), do: {:noreply, turn(socket, shutter: v)}

  # Lock On steers from the camera's pictures where they arrive: on the camera's own machine
  def handle_event("lock", _, %{assigns: %{cam: %{node: n}}} = socket) when n != node() do
    {:noreply, assign(socket, notice: "Lock On runs on the machine the camera is on: open it there")}
  end

  def handle_event("lock", %{"target" => t}, socket) do
    target = if t == "star", do: :star, else: :bright

    notice =
      case socket.assigns.selected &&
             LockOn.start(socket.assigns.selected, source: :still, target: target) do
        :ok -> nil
        {:error, why} -> why
        nil -> "No mount connected"
      end

    StillCamera.continuous(true)
    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("solving", %{"on" => on}, socket) do
    safe(fn -> StillCamera.solving(on == "true", on: socket.assigns.cam[:node]) end)
    {:noreply, socket}
  end

  def handle_event("release", _, socket) do
    LockOn.release()
    {:noreply, socket}
  end

  def handle_event("stop", _, socket) do
    LockOn.release("STOP was pressed")
    Controller.Stop.all()
    {:noreply, assign(socket, notice: "Stopped")}
  end

  defp turn(socket, settings) do
    me = self()
    on = socket.assigns.cam[:node]
    Task.start(fn -> send(me, {:set_done, StillCamera.set(settings, on)}) end)
    assign(socket, turning: true, notice: nil)
  end

  defp parse_iso("auto"), do: :auto
  defp parse_iso(v), do: String.to_integer(v)

  # -- render ----------------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns =
      assign(assigns,
        settings: get_in(assigns.cam, [:camera, :settings]) || %{},
        isos: @isos,
        shutters: @shutters
      )

    ~H"""
    <.page id="still-camera" night={@night}>
      <:header>
        <.back :if={@live_action == :index} navigate={~p"/"} label="Home" section={section(@cam)} />
        <.back :if={@live_action != :index} patch={~p"/cameras/stills"} label="Telescope Camera" />
        <.title>{screen_title(@live_action)}</.title>
        <.actions>
          <.help href={help_href(@live_action)} label={help_label(@live_action)} /><.stop />
        </.actions>
      </:header>

      <p :for={line <- trouble(@cam)} class="hint tone-caution" role="status">{line}</p>

      <%!-- the picture takes the room on every screen; what this screen does with it beside (on a phone, below) --%>
      <.split :if={@cam.camera}>
        <:main>
          <.shot cam={@cam} now_ms={@now_ms} focus={@live_action == :index} />
        </:main>
        <:side>
          <p :if={StillCamera.remote?(@cam)} class="hint" role="status">This camera is on {host(@cam)}. Pictures and exposure work from here.</p>
          <.camera :if={@live_action == :index} cam={@cam} lock={@lock} settings={@settings} />
          <.exposure :if={@live_action == :exposure} cam={@cam} settings={@settings} isos={@isos} shutters={@shutters} turning={@turning} />
          <%!-- the lock and the solver's queue live on the machine the camera is on: from another, a way there --%>
          <.elsewhere :if={@live_action in [:lock, :solving] and StillCamera.remote?(@cam)} cam={@cam} action={@live_action} />
          <.lock :if={@live_action == :lock and not StillCamera.remote?(@cam)} lock={@lock} selected={@selected} />
          <.solving :if={@live_action == :solving and not StillCamera.remote?(@cam)} cam={@cam} plates={@plates} now_ms={@now_ms} selected={@selected} />
        </:side>
      </.split>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # "Cameras · ILCE-6000": the section, and the camera's own name as it spells it
  defp section(%{camera: %{} = c}), do: "Cameras · #{c[:model] || c[:id]}"
  defp section(_), do: "Cameras"

  defp help_href(:exposure), do: ~p"/docs/still-camera#exposure"
  defp help_href(:lock), do: ~p"/docs/still-camera#lock-on"
  defp help_href(:solving), do: ~p"/docs/still-camera#plate-solving"
  defp help_href(_), do: ~p"/docs/still-camera"

  defp help_label(:exposure), do: "exposure"
  defp help_label(:lock), do: "Lock On"
  defp help_label(:solving), do: "plate solving"
  defp help_label(_), do: "the telescope camera"

  # The latest picture, on every screen: how long ago it was taken, what is in it, and on the
  # camera's own screen the number to focus by. Only the facts are a live region: an age that
  # counts up would be read out every second.
  attr :cam, :map, required: true
  attr :now_ms, :integer, required: true
  attr :focus, :boolean, default: false

  defp shot(assigns) do
    assigns = assign(assigns, last: assigns.cam.last)

    ~H"""
    <section class="scope-frame" aria-label="latest picture">
      <img
        :if={@last && @last[:w]}
        src={StillCamera.src(@cam, @last.seq)}
        alt={"Latest picture: #{caption(@last)}"}
      />
      <div :if={!(@last && @last[:w])} class="scope-frame-empty">
        <p class="dim">{if @cam.busy, do: "The first picture is on its way", else: "No picture yet. Tap Take Picture."}</p>
      </div>
      <p :if={@last} class="dim">
        <span>Taken {Pictures.age_words(@last, @now_ms)}</span><span :if={caption(@last) != ""}> · </span><span role="status">{caption(@last)}</span>
      </p>
      <%!-- the picture being taken, stage by stage, while this one stays on the screen --%>
      <Pictures.taking :if={@cam.busy} shot={@cam[:shot]} now_ms={@now_ms} />
      <%!-- why the last picture isn't counted as a good one, a line each; gone with the next good picture --%>
      <p :for={line <- uncounted(@last)} class="hint" role="status">{line}</p>
      <%!-- the number to focus by, on a line of its own; under it what to do, with its ? at the row's end (UI.setting's layout) --%>
      <p :if={@last && @focus} class="lock-line" role="status">{star_size_line(@last)}</p>
      <div :if={@last && @focus} class="setting">
        <div class="setting-text">
          <span>Smaller is sharper. Turn the focus knob a little, take a picture, compare.</span>
        </div>
        <span class="setting-action">
          <.help href={~p"/docs/still-camera#focusing"} label="focusing" />
        </span>
      </div>
      <p :if={@focus && @cam[:free_mb]} class={["dim", @cam.room_for < 20 && "tone-caution"]}>{card_line(@cam)}</p>
    </section>
    """
  end

  # the camera's own screen: a picture now, or one after another; everything else is a screen away
  attr :cam, :map, required: true
  attr :lock, :map, required: true
  attr :settings, :map, required: true

  defp camera(assigns) do
    ~H"""
    <div class="focus-keys">
      <.btn variant="primary" phx-click="shoot" disabled={@cam.busy}>
        {if @cam.busy, do: "Taking…", else: "Take Picture"}
      </.btn>
      <.btn on={@cam.shooting} phx-click="continuous" phx-value-on={to_string(!@cam.shooting)}>
        {if @cam.shooting, do: "Shooting On", else: "Shoot Continuously"}
      </.btn>
    </div>
    <p :if={@cam.why} class="hint tone-caution" role="status">{@cam.why}</p>

    <.items label="more">
      <.link_item patch={~p"/cameras/stills/exposure"} label="Exposure" detail={exposure_words(@settings)} />
      <.link_item patch={~p"/cameras/stills/lock"} label="Lock On" detail={if StillCamera.remote?(@cam), do: "On #{host(@cam)}", else: lock_line(@lock)} />
      <.link_item patch={~p"/cameras/stills/solving"} label="Plate Solving" detail={solve_line(@cam)} />
    </.items>
    """
  end

  # the host of the machine the camera is on ("observatory.local")
  defp host(%{node: n}), do: n |> Atom.to_string() |> String.split("@") |> List.last()
  defp host(_), do: "this machine"

  attr :cam, :map, required: true
  attr :action, :atom, required: true

  defp elsewhere(assigns) do
    ~H"""
    <div class="state-line">
      <strong>{screen_title(@action)} runs on {host(@cam)}</strong>
      <span>It works from the camera's pictures where they arrive, on the machine the camera is plugged into.</span>
    </div>
    <.row><.btn variant="primary" href={"http://#{host(@cam)}/cameras/stills/#{@action}"}>Open It on {host(@cam)} ›</.btn></.row>
    """
  end

  attr :cam, :map, required: true
  attr :settings, :map, required: true
  attr :isos, :list, required: true
  attr :shutters, :list, required: true
  attr :turning, :boolean, default: false

  defp exposure(assigns) do
    ~H"""
    <p class="lock-line" role="status">{exposure_words(@settings)}{if @turning, do: " · turning the dial…", else: ""}</p>
    <.rates label="ISO" class="rates-4">
      <:opt :for={{lbl, v} <- @isos} on={@settings[:iso] == v} click="iso" value={%{iso: v}}>
        {lbl}
      </:opt>
    </.rates>
    <.rates label="shutter speed, in seconds" class="rates-4">
      <:opt :for={v <- @shutters} on={@settings[:shutter] == v} click="shutter" value={%{shutter: v}}>
        {v}
      </:opt>
    </.rates>
    <.row>
      <.btn variant="primary" phx-click="shoot" disabled={@cam.busy}>
        {if @cam.busy, do: "Taking…", else: "Take Picture"}
      </.btn>
    </.row>
    <p :if={@cam.why} class="hint tone-caution" role="status">{@cam.why}</p>
    <.hint>Shutter speed is in seconds. A longer shutter or a higher ISO shows more stars.</.hint>
    """
  end

  attr :lock, :map, required: true
  attr :selected, :string, default: nil

  defp lock(assigns) do
    ~H"""
    <p class="lock-line" role="status">{lock_line(@lock)}</p>
    <p :if={@lock.state in [:holding, :coasting] && @lock[:error_px]} class="dim">
      {hold_line(@lock)}
    </p>
    <.row>
      <.btn
        :if={@lock.state == :off}
        variant="primary"
        phx-click="lock"
        phx-value-target="bright"
        disabled={!@selected}
      >
        Lock On the Bright Target
      </.btn>
      <.btn
        :if={@lock.state == :off}
        phx-click="lock"
        phx-value-target="star"
        disabled={!@selected}
      >
        Lock On a Star
      </.btn>
      <.btn :if={@lock.state != :off} phx-click="release">Release</.btn>
    </.row>
    <.hint>
      Measures how the target drifts and how each motor moves the picture, then steers both. No polar alignment needed.
    </.hint>
    """
  end

  attr :cam, :map, required: true
  attr :plates, :list, required: true
  attr :now_ms, :integer, required: true
  attr :selected, :string, default: nil

  defp solving(assigns) do
    ~H"""
    <p class="lock-line" role="status">{solve_line(@cam)}</p>
    <.row>
      <.btn on={@cam[:solving] == true} phx-click="solving" phx-value-on={to_string(@cam[:solving] != true)}>
        {if @cam[:solving], do: "Solving On", else: "Solve Pictures"}
      </.btn>
    </.row>
    <.hint>
      Each picture is plate solved on the box: where the telescope pointed, to a few arcseconds. Solved pictures add to the mount's alignment.
    </.hint>

    <%!-- every picture in the solver's queue, newest first: the stage it is at and its time, or how it ended --%>
    <.card :if={@plates != []} title="Pictures">
      <Pictures.solves plates={@plates} now_ms={@now_ms} />
    </.card>

    <.items label="alignment">
      <.link_item
        navigate={if @selected, do: ~p"/align/camera/#{@selected}", else: ~p"/align/camera"}
        label="Align with the Camera"
        detail="Takes the pictures and moves the telescope between them, until four agree"
      />
    </.items>
    """
  end

  # what keeps the camera from working, one calm line each
  defp trouble(%{camera: nil, seen: seen}) do
    case Enum.filter(seen, & &1[:says]) do
      [] ->
        [
          "No stills camera: plug the Sony into the box in PC Remote mode (switch it on first, then plug in the cable). It shows up here by itself."
        ]

      lines ->
        Enum.map(lines, & &1.says)
    end
  end

  defp trouble(%{seen: seen}),
    do: seen |> Enum.filter(&(&1[:says] && &1[:mode] != :ptp)) |> Enum.map(& &1.says)

  # what is in the picture: its files, how bright the sky is, what was found
  defp caption(r) do
    [
      r[:names] && Enum.join(r.names, " + "),
      r[:background] && "background #{round(r.background)} of 255",
      bright_words(r[:bright]),
      stars_words(r[:stars])
    ]
    |> Enum.filter(& &1)
    |> Enum.join(" · ")
  end

  defp exposure_words(settings) do
    "ISO #{iso_words(settings[:iso])} · #{settings[:shutter] || "?"} s · #{settings[:quality] || "?"}"
  end

  # Why the last picture is kept but not counted as a good one (`StillCamera.status().good`), a
  # line for each reason.
  defp uncounted(last) when is_map(last), do: Enum.filter([settling_line(last), cloud_line(last)], & &1)
  defp uncounted(_), do: []

  defp settling_line(%{settling: true} = last) do
    case last[:since_slew_s] do
      s when is_number(s) and s > 0 -> "Mount settling: taken #{tenths(s)} s after a slew. Kept, not counted"
      _ -> "Mount slewing during the exposure. Kept, not counted"
    end
  end

  defp settling_line(_), do: nil

  # how much of their light the stars have lost against the clearest picture of this field; thin
  # while they keep more than half of it
  defp cloud_line(%{cloud: true, transparency: t}) when is_number(t) do
    dimmer = round((1 - t) * 100)
    "#{if dimmer < 50, do: "Thin cloud", else: "Cloud"}: stars #{dimmer} percent dimmer. Kept, not counted"
  end

  defp cloud_line(%{cloud: true}), do: "Cloud: no stars left to measure. Kept, not counted"
  defp cloud_line(_), do: nil

  # How wide the stars are, the number to focus by: this picture's, the picture before's (so which
  # way a turn of the knob went is plain), and how many stars it is from. In arcseconds once the
  # focal length is known, in pixels of the measured copy until then.
  defp star_size_line(%{star_size: %{n: n} = now} = last) do
    {unit, value} = if is_number(now[:arcsec]), do: {"arcsec", now.arcsec}, else: {"px", now[:px]}

    was =
      case last[:star_size_was] do
        %{arcsec: a} when unit == "arcsec" and is_number(a) -> ", was #{tenths(a)}"
        %{px: p} when unit == "px" and is_number(p) -> ", was #{tenths(p)}"
        _ -> ""
      end

    "Star size #{tenths(value)} #{unit}#{was} (#{stars_words(n)})"
  end

  defp star_size_line(_), do: "Star size: no stars to measure"

  defp tenths(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp tenths(_), do: "?"

  # where the last picture's plate stands, in one line
  defp solve_line(%{solve: %{state: :solved, seq: n, solution: %{ra_deg: ra, dec_deg: dec} = sol}}) do
    [
      "Picture #{n}: RA #{hms(ra)}, Dec #{dms(dec)}",
      is_number(sol[:width_deg]) && is_number(sol[:height_deg]) && "#{fmt(sol.width_deg)}° × #{fmt(sol.height_deg)}°",
      is_integer(sol[:stars]) && "#{sol.stars} stars",
      is_number(sol[:seconds]) && "#{:erlang.float_to_binary(sol.seconds / 1, decimals: 1)} s"
    ]
    |> Enum.filter(& &1)
    |> Enum.join(" · ")
  end

  defp solve_line(%{solve: %{state: :failed, seq: n, reason: why}}), do: "Picture #{n} not solved: #{solve_words(why)}"
  defp solve_line(%{solve: %{state: st, seq: n}}) when st in [:queued, :solving], do: "Solving picture #{n}…"
  defp solve_line(%{solving: true}), do: "On: the next picture is solved"
  defp solve_line(_), do: "Off"

  defp solve_words("too_few_stars"), do: "too few stars. A longer shutter or a higher ISO shows more"
  defp solve_words("no_solution"), do: "stars, but none that match the sky"
  defp solve_words("below_horizon"), do: "the only match was below the horizon"
  defp solve_words("timeout"), do: "the solver ran out of time"
  defp solve_words("deadline"), do: "the finder solve missed its deadline. The model's aim stands"
  defp solve_words("no_solver"), do: "no plate solver on this box"
  defp solve_words("moving"), do: "the mount was slewing"
  defp solve_words(why), do: to_string(why)

  defp hms(ra) do
    s = round(ra / 15 * 3600)
    "#{pad(div(s, 3600))}h #{pad(rem(div(s, 60), 60))}m #{pad(rem(s, 60))}s"
  end

  defp dms(dec) do
    s = round(abs(dec) * 3600)
    "#{if dec < 0, do: "−", else: "+"}#{pad(div(s, 3600))}° #{pad(rem(div(s, 60), 60))}′ #{pad(rem(s, 60))}″"
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp card_line(%{free_mb: mb, room_for: n}) do
    free = if mb >= 1000, do: "#{Float.round(mb / 1000, 1)} GB", else: "#{mb} MB"
    "SD card: #{free} free, room for #{if n == 1, do: "1 picture", else: "about #{n} pictures"}"
  end

  defp bright_words(%{fraction: f, edge: true}),
    do: "bright target, #{pct(f)} of the picture, cut by the edge"

  defp bright_words(%{fraction: f}), do: "bright target, #{pct(f)} of the picture"
  defp bright_words(_), do: nil

  defp stars_words(1), do: "1 star"
  defp stars_words(n) when is_integer(n) and n > 1, do: "#{n} stars"
  defp stars_words(_), do: nil

  defp pct(f), do: "#{round(f * 100)}%"

  defp iso_words(:auto), do: "Auto"
  defp iso_words(nil), do: "?"
  defp iso_words(v), do: "#{v}"

  defp lock_line(%{state: :off, why: why}) when why in [nil, "not started", "not running"],
    do: "Off"

  defp lock_line(%{state: :off, why: why}), do: "Off: #{why}"
  defp lock_line(%{state: st, why: why}), do: "#{state_words(st)}: #{why}"

  defp state_words(:calibrating), do: "Calibrating"
  defp state_words(:holding), do: "Holding"
  defp state_words(:coasting), do: "Target hidden"
  defp state_words(:lost), do: "Target lost"
  defp state_words(:waiting), do: "Waiting for pictures"
  defp state_words(:stepped_aside), do: "Pad in use"
  defp state_words(:resuming), do: "Picking up"
  defp state_words(other), do: to_string(other)

  defp hold_line(%{error_px: {ex, ey}, rates: {ra, dec}}) do
    "#{round(:math.sqrt(ex * ex + ey * ey))} px off its spot · RA #{fmt(ra)}× · Dec #{fmt(dec)}×"
  end

  defp hold_line(_), do: nil

  defp fmt(x), do: :erlang.float_to_binary(x / 1, decimals: 2)

  defp safe(fun) do
    fun.()
  catch
    _, _ -> nil
  end
end
