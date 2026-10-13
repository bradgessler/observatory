defmodule Controller.StillCameraLive do
  @moduledoc """
  The camera on the telescope when it is a stills camera (a Sony a6000 in PC
  Remote): the same page a video camera gets, with frames that come seconds
  or minutes apart. So the latest picture is always on it, with how long ago
  it was taken.

  One job a screen:

    * `/cameras/stills`: the picture, and beside it everything about taking the next one: a
      picture now or one after another, ISO and shutter speed (the next picture takes them; with a starting exposure
      suggested for what the mount is tracking),
      whether every picture is solved, the picture in flight stage by stage, and the roll of
      the last few, any of which can be looked at again
    * `/cameras/stills/lock`: Lock On, both motors steered from these pictures to hold the target still
    * `/cameras/stills/solving`: the plate solver's queue, where each picture's solve stands

  The two panels open in the column beside the picture and close right there.

  Telescope Camera (`/cameras/telescope`) sends people here when this is the
  camera on the telescope. The camera is the server's
  (`Controller.StillCamera`); every phone sees the same pictures and the same lock.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{LockOn, Plates, Settings, StillCamera}
  alias Controller.Components.Pictures
  alias Controller.Sky.{Catalog, Ephemeris, Exposure, Pointing, Tracker}

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
      # what the mount is tracking: the Exposure screen suggests an exposure for it
      Telescope.subscribe("tracker")
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
       # a starting exposure for what the mount is tracking (`Sky.Exposure`), nil while it tracks nothing
       suggest: suggest(selected && safe(fn -> Tracker.status(selected) end)),
       now_ms: System.system_time(:millisecond),
       notice: nil,
       turning: false,
       # the roll: the picture this viewer is looking at (its number), or nil for the latest as it comes
       picked: nil,
       # the bar of the exposure in flight: which one it is for, and how far in it was when first drawn
       bar: nil
     )}
  end

  @impl true
  def handle_params(_params, _uri, socket), do: {:noreply, assign(socket, page_title: screen_title(socket.assigns.live_action))}

  defp screen_title(:lock), do: "Lock On"
  defp screen_title(:solving), do: "Plate Solving"
  defp screen_title(_), do: "Telescope Camera"

  # the solver's queue for this mount, newest first
  defp plates(nil), do: []
  defp plates(id), do: Enum.reverse((safe(fn -> Plates.view(id) end) || %{})[:plates] || [])

  # another machine's simulated camera is never this page's camera (StillCamera.listed?/2)
  @impl true
  def handle_info({:still_camera, cam}, socket) do
    cam = StillCamera.prefer(socket.assigns.cam, cam)
    # a picture that has left the roll is no longer the one being looked at
    picked = if socket.assigns.picked && Enum.any?(cam[:recent] || [], &(&1.seq == socket.assigns.picked)), do: socket.assigns.picked
    {:noreply, assign(socket, cam: cam, picked: picked, bar: bar(socket.assigns.bar, cam[:shot]))}
  end

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

  # the telescope's optics changed (a solve measured the focal length): the suggestion is worked out again
  def handle_info({:settings, key, _}, %{assigns: %{selected: id}} = socket) when key in ["aperture_mm", "focal_length_mm"] and is_binary(id),
    do: {:noreply, assign(socket, suggest: suggest(safe(fn -> Tracker.status(id) end)))}

  # a hold started, ended or moved to another target: the suggestion follows it; its every tick doesn't
  def handle_info({:tracker, id, status}, %{assigns: %{selected: id}} = socket) do
    if get_in(status || %{}, [:target, :id]) == (socket.assigns.suggest || %{})[:id],
      do: {:noreply, socket},
      else: {:noreply, assign(socket, suggest: suggest(status))}
  end

  def handle_info({:set_done, result}, socket) do
    notice =
      if match?({:error, _}, result),
        do: "The camera didn't take the setting: #{inspect(elem(result, 1))}"

    {:noreply, assign(socket, turning: false, notice: notice)}
  end

  def handle_info(_, socket), do: {:noreply, socket}

  # The exposure's bar runs by itself in the browser (CSS), so it is smooth. It is started once
  # per exposure: how far in the exposure was when this page first saw it is worked out then and
  # kept, or every redraw would start the bar again.
  defp bar(%{key: key} = bar, %{stage: :exposing, seq: seq}) when key == seq, do: bar

  defp bar(_, %{stage: :exposing, seq: seq, exposure_ms: ms, since_ms: since}) when is_number(ms) and ms >= 1_000,
    do: %{key: seq, ms: round(ms), in_ms: max(System.system_time(:millisecond) - since, 0)}

  defp bar(_, _), do: nil

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

  # the two dropdowns: whichever was changed is turned; the next picture takes it
  def handle_event("exposure", %{"_target" => ["iso"], "iso" => v}, socket), do: {:noreply, turn(socket, iso: parse_iso(v))}
  def handle_event("exposure", %{"_target" => ["shutter"], "shutter" => v}, socket), do: {:noreply, turn(socket, shutter: v)}
  def handle_event("exposure", _, socket), do: {:noreply, socket}

  # the roll: look at one of the last pictures, or go back to the latest as it comes
  def handle_event("pick", %{"seq" => seq}, socket), do: {:noreply, assign(socket, picked: String.to_integer(seq))}
  def handle_event("latest", _, socket), do: {:noreply, assign(socket, picked: nil)}

  # Use It: both dials to the suggested exposure, as the server worked it out (nothing is taken from the page)
  def handle_event("use_exposure", _, %{assigns: %{suggest: %{advice: a}}} = socket), do: {:noreply, turn(socket, iso: a.iso, shutter: a.shutter)}
  def handle_event("use_exposure", _, socket), do: {:noreply, socket}

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

  # A starting exposure for what the mount is tracking, among the ISOs and shutter speeds this
  # screen's dials offer: `%{id, name, advice}`, or nil when it tracks nothing the catalogue knows
  # (the tracker keeps the target's id, name and place; what kind of thing it is comes from the catalogue).
  defp suggest(%{target: %{id: id}}) when is_binary(id) do
    obj = Catalog.object(id) || Enum.find(safe(fn -> Ephemeris.objects(DateTime.utc_now(), Pointing.site()) end) || [], &(&1.id == id))

    case Exposure.tonight(obj, shutters: @shutters, isos: for({_, iso} <- @isos, is_integer(iso), do: iso)) do
      nil -> nil
      # "Moon · last quarter" is the Moon
      advice -> %{id: id, name: obj.name |> String.split(" · ", parts: 2) |> hd(), advice: advice}
    end
  end

  defp suggest(_), do: nil

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

      <%!-- One row over the picture: take one, keep taking them, and what the next one is taken at.
            Under it the picture, with the pictures already taken beside it (on a phone, below). --%>
      <.controls :if={@cam.camera && @live_action == :index} cam={@cam} settings={@settings} isos={@isos} shutters={@shutters} turning={@turning} suggest={@suggest} />
      <.split :if={@cam.camera}>
        <:main>
          <.shot cam={@cam} now_ms={@now_ms} focus={@live_action == :index} picked={@picked} />
        </:main>
        <:side>
          <%!-- a panel opened from this column closes right here, where the hand already is --%>
          <div :if={@live_action != :index} class="panel-head">
            <h2>{screen_title(@live_action)}</h2>
            <.link patch={~p"/cameras/stills"} class="btn panel-close" aria-label={"Close #{screen_title(@live_action)}"}><span aria-hidden="true">✕ </span>Close</.link>
          </div>
          <.camera :if={@live_action == :index} cam={@cam} lock={@lock} settings={@settings} isos={@isos} shutters={@shutters} turning={@turning} picked={@picked} bar={@bar} now_ms={@now_ms} suggest={@suggest} />
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

  defp help_href(:lock), do: ~p"/docs/still-camera#lock-on"
  defp help_href(:solving), do: ~p"/docs/still-camera#plate-solving"
  defp help_href(_), do: ~p"/docs/still-camera"

  defp help_label(:lock), do: "Lock On"
  defp help_label(:solving), do: "plate solving"
  defp help_label(_), do: "the telescope camera"

  # The latest picture, on every screen: how long ago it was taken, what is in it, and on the
  # camera's own screen the number to focus by. Only the facts are a live region: an age that
  # counts up would be read out every second.
  attr :cam, :map, required: true
  attr :now_ms, :integer, required: true
  attr :focus, :boolean, default: false

  attr :picked, :integer, default: nil

  defp shot(assigns) do
    old = assigns.picked && Enum.find(assigns.cam[:recent] || [], &(&1.seq == assigns.picked))
    assigns = assign(assigns, last: assigns.cam.last, old: old)

    ~H"""
    <section class="scope-frame" aria-label={if @old, do: "picture #{@old.seq}", else: "latest picture"}>
      <%!-- one of the roll's pictures, looked at again: it stays until Latest, or until it leaves the roll --%>
      <img :if={@old} src={StillCamera.src_of(@cam, @old.seq)} alt={"Picture #{@old.seq}: #{roll_words(@old)}"} />
      <p :if={@old} class="shot-line is-old">
        <span>Picture {@old.seq} · taken {Pictures.age_words(@old, @now_ms)} · {roll_words(@old)}</span>
        <button type="button" class="btn shot-latest" phx-click="latest">Latest</button>
      </p>

      <img
        :if={!@old && @last && @last[:w]}
        src={StillCamera.src(@cam, @last.seq)}
        alt={"Latest picture: #{caption(@last)}"}
      />
      <div :if={!@old && !(@last && @last[:w])} class="scope-frame-empty">
        <p class="dim">{cond do
          @cam.busy -> "The first picture is on its way"
          not ready?(@cam) -> "The camera is not ready"
          true -> "No picture yet. Tap Take Picture."
        end}</p>
      </div>
      <p :if={!@old && @last} class="shot-line dim">
        <span>Taken {Pictures.age_words(@last, @now_ms)}</span><span :if={caption(@last) != ""}> · </span><span role="status">{caption(@last)}</span>
      </p>
      <%!-- why the last picture isn't counted as a good one, a line each; gone with the next good picture --%>
      <p :for={line <- uncounted(@last)} :if={!@old} class="hint" role="status">{line}</p>
      <%!-- the number to focus by, on a line of its own; under it what to do, with its help at the row's end --%>
      <p :if={@last && @focus && !@old} class="lock-line" role="status">{star_size_line(@last)}</p>
      <div :if={@last && @focus && !@old} class="setting">
        <div class="setting-text">
          <span>Smaller is sharper. Turn the focus knob a little, take a picture, compare.</span>
        </div>
        <span class="setting-action">
          <.help href={~p"/docs/still-camera#focusing"} label="focusing" />
        </span>
      </div>
    </section>
    """
  end

  # "06:28:23 UTC · ISO 6400 · 15 s · 40 stars": one of the roll's pictures in a line
  defp roll_words(r) do
    [
      match?(%DateTime{}, r[:at]) && Calendar.strftime(r.at, "%H:%M:%S UTC"),
      r[:iso] && "ISO #{iso_words(r.iso)}",
      r[:shutter] && "#{r.shutter} s",
      stars_words(r[:stars])
    ]
    |> Enum.filter(& &1)
    |> Enum.join(" · ")
  end

  # The row over the picture. Left to right: the two things you do (take one; keep taking them),
  # then what the next picture is taken at (ISO, shutter speed), then whether each is plate solved.
  # Under the row, one line that keeps its height: why nothing is being taken, or a dial turning,
  # or a starting exposure for what the mount tracks, with the key that sets it.
  attr :cam, :map, required: true
  attr :settings, :map, required: true
  attr :isos, :list, required: true
  attr :shutters, :list, required: true
  attr :turning, :boolean, default: false
  attr :suggest, :map, default: nil

  defp controls(assigns) do
    ~H"""
    <div class="cam-controls" role="group" aria-label="taking pictures">
      <.btn variant="primary" class="cam-take" phx-click="shoot" disabled={@cam.busy or not ready?(@cam)}>Take Picture</.btn>
      <button type="button" class="switch-row" role="switch" aria-checked={to_string(@cam.shooting == true)} phx-click="continuous" phx-value-on={to_string(!@cam.shooting)}>
        <span>Keep taking pictures</span>
        <span class="switch-state"><span class="switch-word">{if @cam.shooting, do: "On", else: "Off"}</span><i class="switch-knob" aria-hidden="true"></i></span>
      </button>
      <form phx-change="exposure" class="next-shot-form" aria-label="the next picture's exposure">
        <label>
          <span>ISO</span>
          <select name="iso" class="field">
            <option :for={{lbl, v} <- options(@isos, @settings[:iso])} value={to_string(v)} selected={@settings[:iso] == v}>{lbl}</option>
          </select>
        </label>
        <label>
          <span>Shutter speed</span>
          <select name="shutter" class="field">
            <option :for={v <- shutter_options(@shutters, @settings[:shutter])} value={v} selected={@settings[:shutter] == v}>{v} s</option>
          </select>
        </label>
      </form>
      <button type="button" class="switch-row" role="switch" aria-checked={to_string(@cam[:solving] == true)} phx-click="solving" phx-value-on={to_string(@cam[:solving] != true)}>
        <span>Plate solve each picture</span>
        <span class="switch-state"><span class="switch-word">{if @cam[:solving], do: "On", else: "Off"}</span><i class="switch-knob" aria-hidden="true"></i></span>
      </button>
    </div>
    <p class="cam-note" role="status">
      <span :if={@cam.why} class="tone-caution">{@cam.why}</span>
      <span :if={!@cam.why && @turning}>Turning the camera's dial…</span>
      <%!-- the mount is tracking something: a starting exposure for it, and the one key that sets it (#117) --%>
      <span :if={!@cam.why && !@turning && @suggest} class="cam-suggest" title={@suggest.advice.why}>
        Suggested for {@suggest.name}: {Exposure.words(@suggest.advice)}
        <.btn :if={!in_use?(@settings, @suggest)} phx-click="use_exposure" aria-label={"Use it: set #{Exposure.words(@suggest.advice)}"}>Use It</.btn>
        <span :if={in_use?(@settings, @suggest)}>· set <span aria-hidden="true">✓</span></span>
        <.link href={~p"/docs/still-camera#suggested-exposure"}>Why</.link>
      </span>
    </p>
    """
  end

  # Beside the picture: the picture in flight, the roll of the last few, the camera's own facts,
  # and the two panels a tap away.
  attr :cam, :map, required: true
  attr :lock, :map, required: true
  attr :settings, :map, required: true
  attr :isos, :list, required: true
  attr :shutters, :list, required: true
  attr :turning, :boolean, default: false
  attr :picked, :integer, default: nil
  attr :bar, :map, default: nil
  attr :now_ms, :integer, required: true
  attr :suggest, :map, default: nil

  defp camera(assigns) do
    ~H"""
    <%!-- the roll: the picture in flight on top, in a slot that keeps its size; then the last few, newest
          first. Tap one to look at it again. --%>
    <section class="roll" aria-labelledby="roll-h">
      <h2 id="roll-h" class="now-h">Pictures</h2>
      <div class="roll-now">
        <strong role="status">{if @cam.busy, do: Pictures.shot_words(@cam[:shot]), else: "Ready"}</strong>
        <span class="dim">{if @cam.busy, do: flight_words(@cam[:shot], @settings), else: idle_words(@cam, @settings)}</span>
        <span class="shot-bar" aria-hidden="true">
          <i :if={@bar && @cam.busy && match?(%{stage: :exposing}, @cam[:shot])} id={"shot-bar-#{@bar.key}"} style={"animation-duration: #{@bar.ms}ms; animation-delay: -#{@bar.in_ms}ms"}></i>
        </span>
      </div>
      <ol :if={(@cam[:recent] || []) != []} class="roll-list" aria-label="the last pictures, newest first">
        <li :for={r <- @cam[:recent] || []}>
          <button type="button" class={["roll-pic", @picked == r.seq && "picked"]} phx-click="pick" phx-value-seq={r.seq} aria-pressed={to_string(@picked == r.seq)} aria-label={"Look at picture #{r.seq}"}>
            <img src={StillCamera.src_of(@cam, r.seq)} alt="" loading="lazy" />
            <span class="roll-text"><strong>Picture {r.seq}</strong><small>{roll_words(r)}<span :if={solve_mark(@cam, r)} class={["roll-solve", solve_mark(@cam, r) != "solved" && "is-not"]}> · {solve_mark(@cam, r)}</span></small></span>
          </button>
        </li>
      </ol>
    </section>

    <%!-- the camera itself: its battery, its card, what is on it --%>
    <p :if={StillCamera.remote?(@cam)} class="hint" role="status">This camera is on {host(@cam)}. Pictures and exposure work from here.</p>
    <section class="cam-facts" aria-labelledby="cam-facts-h">
      <h2 id="cam-facts-h" class="now-h">Camera</h2>
      <.kv :if={battery(@cam)} label="Battery" value={"#{battery(@cam)}%"} />
      <.kv :if={@settings[:quality]} label="Format" value={to_string(@settings.quality)} />
      <.kv :if={@cam[:free_mb]} label="SD card" value={card_line(@cam)} />
      <.kv :if={@cam[:card]} label="On the card" value={on_card_words(@cam.card)} />
    </section>

    <.items label="more">
      <.link_item patch={~p"/cameras/stills/lock"} label="Lock On" detail={if StillCamera.remote?(@cam), do: "On #{host(@cam)}", else: lock_line(@lock)} />
      <.link_item patch={~p"/cameras/stills/solving"} label="Plate Solving" detail={solve_line(@cam)} />
    </.items>
    """
  end

  # the dropdown's choices, with whatever the camera is set to when that is not one of them
  defp options(isos, now), do: if(is_nil(now) or Enum.any?(isos, fn {_, v} -> v == now end), do: isos, else: isos ++ [{iso_words(now), now}])
  defp shutter_options(shutters, now), do: if(is_nil(now) or now in shutters, do: shutters, else: shutters ++ [now])

  # what the picture in flight is being taken at, beside its stage
  defp flight_words(%{stage: :exposing, exposure_ms: ms}, settings) when is_number(ms), do: "#{shutter_words(ms)} at ISO #{iso_words(settings[:iso])}"
  defp flight_words(%{stage: :downloading, file: n}, settings) when is_integer(n), do: "file #{n} · #{exposure_words(settings)}"
  defp flight_words(_, settings), do: exposure_words(settings)

  # between pictures: the last one's plate solve while it runs, else what the next is taken at
  defp idle_words(%{solve: %{state: st, seq: n}}, _settings) when st in [:queued, :solving], do: "Plate solving picture #{n}"
  defp idle_words(_cam, settings), do: "Next: " <> exposure_words(settings)

  # where a roll picture's plate solve stands (the camera follows the newest one's): a word, or nil
  defp solve_mark(%{solve: %{seq: seq, state: :solved}}, %{seq: seq}), do: "solved"
  defp solve_mark(%{solve: %{seq: seq, state: st}}, %{seq: seq}) when st in [:queued, :solving], do: "solving"
  defp solve_mark(%{solve: %{seq: seq, state: :failed}}, %{seq: seq}), do: "not solved"
  defp solve_mark(_, _), do: nil

  defp shutter_words(ms) when ms >= 1_000, do: "#{round(ms / 1000)} s"
  defp shutter_words(ms), do: "#{round(ms)} ms"

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

  # A camera that is on the cable and answers nothing: say so, and what to do with one's hands.
  # (13 October: a reboot caught the Sony in the middle of sending a picture, and it answered
  # nothing afterwards; the page said "No picture yet. Tap Take Picture".)
  defp trouble(%{camera: %{state: :failed} = c}) do
    ["The camera is not answering#{failed_words(c[:error])}. Unplug its USB cable, switch the camera off and on (and look at its battery), then plug the cable back in. The box picks it up by itself."]
  end

  defp trouble(%{seen: seen}),
    do: seen |> Enum.filter(&(&1[:says] && &1[:mode] != :ptp)) |> Enum.map(& &1.says)

  defp failed_words(:timeout), do: " (it was asked and said nothing)"
  defp failed_words(nil), do: ""
  defp failed_words(other), do: " (#{Controller.Words.error(other)})"

  defp ready?(%{camera: %{state: :ready}}), do: true
  defp ready?(_), do: false

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

  # the camera is already set to the suggested ISO and shutter speed
  defp in_use?(settings, %{advice: a}), do: settings[:iso] == a.iso and settings[:shutter] == a.shutter
  defp in_use?(_, _), do: false

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

  defp card_line(%{free_mb: mb, room_for: n} = cam) do
    total = get_in(cam, [:card, :total_mb])
    "#{size_words(mb)} free#{if total, do: " of #{size_words(total)}", else: ""}, room for #{if n == 1, do: "1 picture", else: "about #{n} pictures"}"
  end

  defp on_card_words(%{pictures: n, pictures_mb: mb}), do: "#{n} #{if n == 1, do: "picture", else: "pictures"}, #{size_words(mb)}"
  defp on_card_words(_), do: "?"

  defp size_words(mb) when mb >= 1000, do: "#{Float.round(mb / 1000, 1)} GB"
  defp size_words(mb), do: "#{mb} MB"

  defp battery(%{camera: %{settings: %{battery: b}}}) when is_number(b), do: round(b)
  defp battery(_), do: nil

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
