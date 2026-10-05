defmodule Controller.StillCameraLive do
  @moduledoc """
  The stills camera on the telescope (a Sony a6000 in PC Remote), on a phone:
  the last picture, ISO and shutter, a picture now or one after another, and
  Lock On: both motors steered from these pictures to hold the target still.

  The camera is the server's (`Controller.StillCamera`); every phone sees the
  same pictures and the same lock.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{LockOn, Settings, StillCamera}

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
    if connected?(socket) do
      StillCamera.subscribe()
      LockOn.subscribe()
      Settings.subscribe()
    end

    mounts = safe(fn -> Mount.list() end) || []
    selected = params["id"] || session["telescope"] || Mount.default(Enum.map(mounts, & &1.id))

    {:ok,
     assign(socket,
       page_title: "Stills Camera",
       night: Settings.get("night", false),
       cam: StillCamera.status(),
       lock: LockOn.status(),
       selected: selected,
       notice: nil,
       turning: false
     )}
  end

  @impl true
  def handle_info({:still_camera, cam}, socket), do: {:noreply, assign(socket, cam: cam)}
  def handle_info({:lock_on, lock}, socket), do: {:noreply, assign(socket, lock: lock)}
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
  def handle_event("shoot", _, socket) do
    StillCamera.shoot()
    {:noreply, socket}
  end

  def handle_event("continuous", %{"on" => on}, socket) do
    StillCamera.continuous(on == "true")
    {:noreply, socket}
  end

  # the dials turn a notch at a time: the page stays live while they do
  def handle_event("iso", %{"iso" => v}, socket), do: {:noreply, turn(socket, iso: parse_iso(v))}
  def handle_event("shutter", %{"shutter" => v}, socket), do: {:noreply, turn(socket, shutter: v)}

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
    StillCamera.solving(on == "true")
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
    Task.start(fn -> send(me, {:set_done, StillCamera.set(settings)}) end)
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
        <.back navigate={~p"/"} label="Home" section="Cameras" />
        <.title>Stills Camera</.title>
        <.actions>
          <.help href={~p"/docs/still-camera"} label="the stills camera" /><.stop />
        </.actions>
      </:header>

      <p :for={line <- trouble(@cam)} class="hint tone-caution" role="status">{line}</p>

      <.split :if={@cam.camera}>
        <:main>
          <section class="scope-frame" aria-label="latest picture">
            <img
              :if={@cam.last && @cam.last[:w]}
              src={~p"/cameras/stills/latest.png?#{[t: @cam.last.seq]}"}
              alt={"Latest picture: #{caption(@cam.last)}"}
            />
            <div :if={!(@cam.last && @cam.last[:w])} class="scope-frame-empty">
              <p class="dim">No picture yet. Tap Take Picture.</p>
            </div>
            <p :if={@cam.last} class="dim" role="status">{caption(@cam.last)}</p>
            <%!-- why the last picture isn't counted as a good one, a line each; gone with the next good picture --%>
            <p :for={line <- uncounted(@cam.last)} class="hint" role="status">{line}</p>
            <%!-- the number to focus by, on a line of its own; under it what to do, with its ? at the row's end (UI.setting's layout) --%>
            <p :if={@cam.last} class="lock-line" role="status">{star_size_line(@cam.last)}</p>
            <div :if={@cam.last} class="setting">
              <div class="setting-text">
                <span>Smaller is sharper. Turn the focus knob a little, take a picture, compare.</span>
              </div>
              <span class="setting-action">
                <.help href={~p"/docs/still-camera#focusing"} label="focusing" />
              </span>
            </div>
            <p :if={@cam[:free_mb]} class={["dim", @cam.room_for < 20 && "tone-caution"]}>{card_line(@cam)}</p>
          </section>
        </:main>
        <:side>
          <div class="focus-keys">
            <.btn variant="primary" phx-click="shoot" disabled={@cam.busy}>
              {if @cam.busy, do: "Taking…", else: "Take Picture"}
            </.btn>
            <.btn on={@cam.shooting} phx-click="continuous" phx-value-on={to_string(!@cam.shooting)}>
              {if @cam.shooting, do: "Shooting On", else: "Shoot Continuously"}
            </.btn>
          </div>
          <p :if={@cam.why} class="hint tone-caution" role="status">{@cam.why}</p>

          <.card title="Lock On">
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
          </.card>

          <.card title="Plate Solve">
            <p class="lock-line" role="status">{solve_line(@cam)}</p>
            <.row>
              <.btn on={@cam[:solving] == true} phx-click="solving" phx-value-on={to_string(@cam[:solving] != true)}>
                {if @cam[:solving], do: "Solving On", else: "Solve Pictures"}
              </.btn>
              <.btn variant="ghost" navigate={~p"/align/photo"}>Alignment Photos</.btn>
            </.row>
            <.hint>
              Each picture is plate solved on the box: where the telescope pointed, to a few arcseconds. Solved pictures add to the mount's alignment.
            </.hint>
          </.card>

          <.card title="Settings">
            <p class="dim">
              ISO {iso_words(@settings[:iso])} · {@settings[:shutter] || "?"} s · {@settings[:quality] ||
                "?"}{if @turning, do: " · turning the dial…", else: ""}
            </p>
            <.rates label="ISO" class="rates-4">
              <:opt :for={{lbl, v} <- @isos} on={@settings[:iso] == v} click="iso" value={%{iso: v}}>
                {lbl}
              </:opt>
            </.rates>
            <.rates label="shutter speed" class="rates-4">
              <:opt
                :for={v <- @shutters}
                on={@settings[:shutter] == v}
                click="shutter"
                value={%{shutter: v}}
              >
                {v}
              </:opt>
            </.rates>
          </.card>
        </:side>
      </.split>

      <.notice notice={@notice} />
    </.page>
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

  defp caption(r) do
    [
      r[:names] && Enum.join(r.names, " + "),
      r[:background] && "background #{round(r.background)} of 255",
      bright_words(r[:bright]),
      stars_words(r[:stars]),
      r[:at] && Calendar.strftime(r.at, "%H:%M:%S UTC")
    ]
    |> Enum.filter(& &1)
    |> Enum.join(" · ")
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
