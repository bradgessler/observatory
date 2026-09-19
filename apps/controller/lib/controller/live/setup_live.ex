defmodule Controller.SetupLive do
  @moduledoc """
  Mount setup, on its own page: home, exact moves, and every mode that changes
  where the scope goes — with the current value shown and a way to undo it.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Modes, Settings}
  alias Controller.Sky.Pointing

  @impl true
  def mount(%{"id" => id}, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("tracker")
    end

    {:ok,
     socket
     |> assign(id: id, ref: nil, snap: nil, notice: nil, goto_deg: "5", night: Settings.get("night", false))
     |> rescan()
     |> load()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.id, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:tracker, id, _}, %{assigns: %{id: id}} = socket), do: {:noreply, load(socket)}
  def handle_info({:tracker, _, _}, socket), do: {:noreply, socket}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, socket |> assign(night: v) |> load()}
  def handle_info({:settings, _key, _v}, socket), do: {:noreply, load(socket)}

  defp rescan(socket) do
    case Enum.find(Mount.list(), &(&1.id == socket.assigns.id)) do
      nil ->
        assign(socket, ref: nil, snap: nil)

      ref ->
        if is_nil(socket.assigns.ref), do: Mount.subscribe(ref)
        assign(socket, ref: ref, snap: safe(fn -> Mount.snapshot(ref) end) |> ok_or_nil())
    end
  end

  defp load(socket) do
    assign(socket,
      steering: steering(socket.assigns.id),
      modes: Modes.active(),
      pointing: Pointing.pointing(),
      offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0}),
      tracking_direction: Settings.get("tracking_direction", "forward"),
      auto_track: Settings.get("auto_track", true),
      limits: Application.get_env(:mount, :limits),
      mount_tilt: Settings.get("mount_tilt_deg", Pointing.site().lat),
      mount_heading: Settings.get("mount_heading_deg", 0)
    )
  end

  # -- events -------------------------------------------------------------------------

  @impl true
  def handle_event("home", _, socket) do
    {:noreply, socket |> run(&Mount.set_home/1, "home set — limits armed") |> load()}
  end

  def handle_event("goto", %{"axis" => axis, "sign" => sign, "deg" => deg}, socket) do
    case Float.parse(deg) do
      {d, _} ->
        d = if sign == "-", do: -d, else: d

        {:noreply,
         socket
         |> assign(goto_deg: deg)
         |> run(&Mount.goto_relative(&1, String.to_existing_atom(axis), d), "moving #{axis} #{d}°")}

      :error ->
        {:noreply, assign(socket, notice: "degrees?")}
    end
  end

  def handle_event("clear_sync", _, socket) do
    Modes.clear_sync()
    {:noreply, socket |> assign(notice: "sync offset cleared") |> load()}
  end

  def handle_event("flip", %{"what" => what}, socket) do
    p = socket.assigns.pointing

    p =
      case what do
        "ra" -> %{p | ha_sign: -p.ha_sign}
        "dec" -> %{p | dec_sign: -p.dec_sign}
      end

    Settings.put("pointing", %{"ha_sign" => p.ha_sign, "dec_sign" => p.dec_sign})
    Modes.clear_sync()
    {:noreply, socket |> assign(notice: "#{what} axis flipped; sync offset cleared") |> load()}
  end

  def handle_event("reset_pointing", _, socket) do
    Modes.reset_pointing()
    {:noreply, socket |> assign(notice: "pointing back to config defaults") |> load()}
  end

  def handle_event("tracking_direction", _, socket) do
    dir = if socket.assigns.tracking_direction == "forward", do: "reverse", else: "forward"
    Settings.put("tracking_direction", dir)
    if socket.assigns.ref, do: safe(fn -> Mount.configure(socket.assigns.ref, tracking_direction: String.to_atom(dir)) end)
    {:noreply, socket |> assign(notice: "tracking direction: #{dir}") |> load()}
  end

  # The physical mount: latitude knob and which way the tripod's north leg points.
  def handle_event("mount_geom", %{"tilt" => t, "heading" => h}, socket) do
    with {tilt, _} <- Float.parse(t), {heading, _} <- Float.parse(h), true <- tilt >= 0 and tilt <= 90 do
      Settings.put("mount_tilt_deg", tilt)
      Settings.put("mount_heading_deg", heading)
      {:noreply, load(socket)}
    else
      _ -> {:noreply, socket}
    end
  end

  def handle_event("auto_track", _, socket) do
    Settings.put("auto_track", !socket.assigns.auto_track)
    {:noreply, load(socket)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp run(%{assigns: %{ref: nil}} = socket, _fun, _ok), do: assign(socket, notice: "no mount")

  defp run(socket, fun, ok_msg) do
    case safe(fn -> fun.(socket.assigns.ref) end) do
      :ok -> assign(socket, notice: ok_msg)
      {:error, :limit} -> assign(socket, notice: "soft limit")
      {:error, e} -> assign(socket, notice: inspect(e))
    end
  end

  defp fmt1(x), do: :erlang.float_to_binary(x / 1, decimals: 1)

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end

  defp ok_or_nil({:error, _}), do: nil
  defp ok_or_nil(v), do: v

  # -- render -------------------------------------------------------------------------

  # How the scope is being steered right now, in the language of #62: which
  # law is in charge, what it is correcting for and by how much, and how the
  # target is being held. One place to look once everything is set up.
  defp steering(id) do
    align = Controller.Sky.Lineup.status(id)
    p = Pointing.pointing()
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})
    off = Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})
    tracker = Controller.Sky.Tracker.status(id)

    law =
      cond do
        align.solved? and align.n >= 3 -> {3, "sky · star-aligned", "gotos and tracking go through the fitted geometry of this mount"}
        align.solved? -> {3, "sky · star-aligned (#{align.n} star#{if align.n == 1, do: "", else: "s"})", "steerable in the sky; a third star would grade it"}
        abs(off["ra"]) > 0.01 or abs(off["dec"]) > 0.01 -> {2, "sky · ideal geometry + sync offset", "assumes the mount is polar-aligned; one star fixed the offsets"}
        true -> {2, "sky · ideal geometry", "assumes the mount is polar-aligned and zeroed upright; no correction yet"}
      end

    corrections =
      [
        if(align.solved?, do: align.axis_words),
        if(align.solved? and align.rms_arcmin, do: "stars agree to #{fmt1(align.rms_arcmin)}′#{if align.good_for != [], do: " · good for " <> Enum.join(align.good_for, ", ")}"),
        if(align.signs_corrected?, do: "an axis sign was corrected from the stars"),
        if(not align.solved? and (abs(off["ra"]) > 0.01 or abs(off["dec"]) > 0.01), do: "sync offset RA #{fmt1(off["ra"])}° · Dec #{fmt1(off["dec"])}°"),
        if(p.ha_sign != base.ha_sign, do: "RA axis sign flipped"),
        if(p.dec_sign != base.dec_sign, do: "Dec axis sign flipped")
      ]
      |> Enum.reject(&is_nil/1)

    tracking =
      cond do
        tracker && tracker.paused -> "model tracker on #{tracker.name} · paused while a hand is on a control"
        tracker -> "model tracker on #{tracker.name} · RA #{fmt1(tracker.ra_rate)}× Dec #{fmt1(tracker.dec_rate)}×#{if tracker.error_arcmin, do: " · #{fmt1(tracker.error_arcmin)}′ off"}"
        true -> nil
      end

    %{law: law, corrections: corrections, tracking: tracking}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="setup" night={@night}>
      <:header>
        <.back navigate={~p"/#{@id}"} label="Keypad" />
        <.title>{@id} · Setup</.title>
        <.actions><.help href={~p"/docs/keypad"} /></.actions>
      </:header>

      <%!-- the one place to see what is steering the scope and what it is correcting for --%>
      <.card title="How It's Steered" class="steering">
        <:aside><.badge on={elem(@steering.law, 0) == 3}>law {elem(@steering.law, 0)}</.badge></:aside>
        <div class="state-line">
          <strong>{elem(@steering.law, 1)}</strong>
          <span class="dim">{elem(@steering.law, 2)}</span>
        </div>
        <ul :if={@steering.corrections != []} class="checklist">
          <li :for={c <- @steering.corrections}>{c}</li>
        </ul>
        <.kv label="tracking" value={@steering.tracking || (if @snap && @snap.tracking != :off, do: "mount's own #{@snap.tracking} rate on RA (law 2)", else: "not tracking")} />
        <.hint>1 raw axes · 2 ideal mount · 3 this mount, as the stars measured it. <.link navigate={~p"/controls/align/#{@id}"}>Star Align</.link> · <.link href={~p"/docs/align"}>?</.link></.hint>
      </.card>

      <.card title="Zero the Axes">
        <:aside>
          <.badge on={@snap && @snap.homed}>{if @snap && @snap.homed, do: "zeroed · limits armed", else: "not zeroed"}</.badge>
        </:aside>
        <.hint>Counterweight straight down, tube along the polar axis, by eye. Arms the cable-safety limits; the stars do the sky.</.hint>
        <.btn phx-click="home" data-confirm="Zero both axes at the current position?">Zero the axes here</.btn>
      </.card>

      <.row>
        <.btn navigate={~p"/bench/position?#{[mount: @id]}"}>Move to an exact angle ›</.btn>
      </.row>

      <.card title="Modes">
        <:aside><.badge :if={@modes == []} on>all stock</.badge><.badge :if={@modes != []} warn>{length(@modes)} on</.badge></:aside>
        <.hint>Each of these changes where the scope goes and shows on every page while on.</.hint>

        <.setting label="Sync offset" value={"RA #{fmt(@offset["ra"])}° · Dec #{fmt(@offset["dec"])}°"}>
          <.btn phx-click="clear_sync" disabled={abs(@offset["ra"]) < 0.01 and abs(@offset["dec"]) < 0.01}>Clear</.btn>
        </.setting>
        <.setting label="RA axis sign" value={to_string(@pointing.ha_sign)}>
          <.btn phx-click="flip" phx-value-what="ra">Flip</.btn>
        </.setting>
        <.setting label="Dec axis sign" value={to_string(@pointing.dec_sign)}>
          <.btn phx-click="flip" phx-value-what="dec">Flip</.btn>
        </.setting>
        <.setting label="Tracking direction" value={@tracking_direction}>
          <.btn phx-click="tracking_direction">Flip</.btn>
        </.setting>
        <.setting label="Auto-track after slew" value={if @auto_track, do: "on", else: "off"}>
          <.btn phx-click="auto_track">{if @auto_track, do: "Turn off", else: "Turn on"}</.btn>
        </.setting>
        <.setting label="Soft limits from home" value={"RA #{lim(@limits, :ra)} · Dec #{lim(@limits, :dec)}"} />
        <.btn variant="ghost" phx-click="reset_pointing">Reset pointing to defaults</.btn>
      </.card>

      <.card title="Mount As It Stands">
        <.hint>What the orb draws. Tilt is the latitude knob on the mount (30° on the bench); heading is where the tripod's north leg points, degrees east of true north. Defaults: site latitude, 0.</.hint>
        <form phx-change="mount_geom" class="horizon">
          <label>tilt °<input name="tilt" inputmode="decimal" value={@mount_tilt} class="field" /></label>
          <label>heading °<input name="heading" inputmode="decimal" value={@mount_heading} class="field" /></label>
        </form>
      </.card>

      <.row>
        <.btn navigate={~p"/devices"}>Devices</.btn>
        <.btn navigate={~p"/sky/#{@id}"}>Sky · Horizon</.btn>
      </.row>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp fmt(x) when x >= 0, do: "+" <> :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)

  defp lim(%{} = l, axis) do
    case l[axis] do
      {lo, hi} -> "#{round(lo)}°…#{round(hi)}°"
      _ -> "off"
    end
  end

  defp lim(_, _), do: "off"
end
