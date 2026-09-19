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
      modes: Modes.active(),
      pointing: Pointing.pointing(),
      offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0}),
      tracking_direction: Settings.get("tracking_direction", "forward"),
      auto_track: Settings.get("auto_track", true),
      limits: Application.get_env(:mount, :limits)
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

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="setup" night={@night}>
      <:header>
        <.back navigate={~p"/#{@id}"} label="keypad" />
        <.title>{@id} · setup</.title>
        <.actions><.help href={~p"/docs/keypad"} /></.actions>
      </:header>

      <.card title="Home">
        <:aside>
          <.badge on={@snap && @snap.homed}>{if @snap && @snap.homed, do: "set · limits armed", else: "not set"}</.badge>
        </:aside>
        <.hint>Counterweight straight down, tube at the pole. Do this before slewing from the sky page.</.hint>
        <.btn phx-click="home" data-confirm="Set the current position as home?">Set home</.btn>
      </.card>

      <.card title="Move exactly">
        <form phx-submit="goto" class="row">
          <input type="hidden" name="axis" value="ra" /><input type="hidden" name="sign" value="+" />
          <input name="deg" inputmode="decimal" value={@goto_deg} aria-label="degrees" class="field" />
          <.btn type="submit">RA +</.btn>
        </form>
        <.row>
          <.btn phx-click="goto" phx-value-axis="ra" phx-value-sign="-" phx-value-deg={@goto_deg}>RA −</.btn>
          <.btn phx-click="goto" phx-value-axis="dec" phx-value-sign="+" phx-value-deg={@goto_deg}>Dec +</.btn>
          <.btn phx-click="goto" phx-value-axis="dec" phx-value-sign="-" phx-value-deg={@goto_deg}>Dec −</.btn>
        </.row>
      </.card>

      <.card title="Modes">
        <:aside><.badge :if={@modes == []} on>all stock</.badge><.badge :if={@modes != []} warn>{length(@modes)} on</.badge></:aside>
        <.hint>Anything here changes where the scope goes. Each shows on every page while it's on.</.hint>

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

      <.row>
        <.btn navigate={~p"/devices"}>Devices</.btn>
        <.btn navigate={~p"/sky/#{@id}"}>Sky · Horizon</.btn>
      </.row>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
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
