defmodule Firmware.Web.BluetoothLive do
  @moduledoc """
  The box's Bluetooth: the batteries it reads (`Firmware.Batteries`, every
  Anker SOLIX in range, nothing to pair), whether the stack is up (and if
  not, why, in one line), the radio it drives, and every device heard
  nearby with its signal and what it broadcasts. Pairing a game pad comes
  next.

  Two keys: Active Scan (20 s of asking devices their names, which slows
  Wi-Fi while it runs) and Restart Radio (the manual path after the radio
  watchdog gives up). Everything else is decided by `Firmware.Bluetooth`.

  Part of the firmware, like the Network page: the radio is the box's.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Firmware.Batteries
  alias Firmware.Bluetooth

  @tick_ms 2_000
  @active_ms 20_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      :timer.send_interval(@tick_ms, :tick)
      # a new reading shows the moment it arrives, on every phone
      Telescope.subscribe("power")
    end

    {:ok,
     socket
     |> assign(page_title: "Bluetooth", night: Settings.get("night", false), notice: nil, active_s: div(@active_ms, 1000))
     |> refresh()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}
  def handle_info({:batteries, list}, socket), do: {:noreply, assign_batteries(socket, list)}

  @impl true
  # STOP is on every page: every mount in reach
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("active_scan", _, socket) do
    notice =
      case Bluetooth.active_scan(@active_ms) do
        :ok -> "Scanning actively for #{div(@active_ms, 1000)} s"
        {:error, _} -> "No adapter to scan with"
      end

    {:noreply, socket |> assign(notice: notice) |> refresh()}
  end

  def handle_event("restart", _, socket) do
    notice = if Bluetooth.restart() == :ok, do: "Restarting the radio", else: "Bluetooth is not running on this box"
    {:noreply, socket |> assign(notice: notice) |> refresh()}
  end

  defp refresh(socket) do
    socket
    |> assign(status: Bluetooth.status(), nearby: Bluetooth.Nearby.list())
    |> assign_batteries(Batteries.list())
  end

  # the words are made here, with the time: a reading's age moves on its own
  defp assign_batteries(socket, list) do
    now = System.monotonic_time(:millisecond)
    assign(socket, batteries: Enum.map(list, &Map.put(&1, :detail, battery_detail(&1, now))))
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="bluetooth" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="System" />
        <.title>Bluetooth</.title>
        <.actions><.help href={~p"/docs/bluetooth"} label="bluetooth" /><.stop /></.actions>
      </:header>

      <.card title="Batteries">
        <.items :if={@batteries != []} label="batteries">
          <.item :for={b <- @batteries} as="li" label={"Battery #{b.n}"} detail={b.detail}>
            <.badge on={b.state == :live} dim={b.state != :live}>{battery_word(b.state)}</.badge>
          </.item>
        </.items>
        <.hint :if={@batteries == [] and @status.state == :running}>
          No Anker SOLIX battery heard yet. One in range shows up here by itself, nothing to pair.
        </.hint>
        <.hint :if={@batteries == [] and @status.state != :running}>
          Batteries are read over Bluetooth, which is not running.
        </.hint>
      </.card>

      <.card title="Radio">
        <:aside><.badge on={@status.state == :running} warn={warn?(@status.state)}>{state_word(@status.state)}</.badge></:aside>
        <div role="status" aria-live="polite">
          <.kv label="Stack" value={stack_words(@status)} />
          <.kv :if={@status.adapter} label={"Adapter " <> Path.basename(@status.adapter.path)} value={@status.adapter.address} />
          <.kv :if={@status.scan} label="Scan" value={scan_words(@status)} />
          <.kv :if={@status.resets > 0} label="Driver resets" value={"#{@status.resets} this boot"} />
          <.kv :if={@status.failures > 0} label="Stack restarts" value={"#{@status.failures} since boot"} />
          <.kv :if={@status.last_error} label="Last stop" value={@status.last_error} />
        </div>
        <div class="flow-actions">
          <button class="btn" phx-click="active_scan" disabled={@status.state != :running or @status.scan == :active}>Active Scan</button>
          <button class="btn" phx-click="restart" disabled={@status.state in [:unavailable, :not_running]}>Restart Radio</button>
        </div>
        <.hint>Active Scan asks each device its name for {@active_s} s. Wi-Fi slows while it runs.</.hint>
      </.card>

      <.card title="Nearby">
        <:aside><span class="dim">{length(@nearby)} heard</span></:aside>
        <.items :if={@nearby != []} label="nearby Bluetooth devices">
          <.item :for={d <- @nearby} as="li" label={d.name || d.address} detail={detail(d)}>
            <.signal percent={percent(d.rssi)} dbm={d.rssi} />
          </.item>
        </.items>
        <.hint :if={@nearby == [] and @status.state == :running}>
          Listening. A device that is not advertising (a battery asleep, a pad not in pairing mode) shows up once it is.
        </.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp warn?({:restarting, _}), do: true
  defp warn?(:radio_failed), do: true
  defp warn?(_), do: false

  defp state_word(:running), do: "On"
  defp state_word({:restarting, _}), do: "Restarting"
  defp state_word(:radio_failed), do: "Failed"
  defp state_word(:no_radio), do: "No radio"
  defp state_word(:unavailable), do: "Off"
  defp state_word(:not_running), do: "Off"
  defp state_word(_), do: "Starting"

  defp stack_words(%{state: :running, adapter: a}), do: a.name
  defp stack_words(%{state: {:restarting, ms}}), do: "Stopped; starting again in #{div(ms, 1000)} s"
  defp stack_words(%{state: :radio_failed, resets: n}), do: "The radio did not come up after #{n} driver resets. Restart Radio to try again."
  defp stack_words(%{state: :no_radio}), do: "No Bluetooth radio on this board. A USB adapter is picked up within a minute of plugging it in."
  defp stack_words(%{state: :unavailable}), do: "Not in this system image"
  defp stack_words(%{state: :not_running}), do: "Not running"
  defp stack_words(_), do: "Starting (waits 20 s after power-on so Wi-Fi joins first)"

  defp scan_words(%{scan: :active, active_left_ms: ms}), do: "Active, #{div(ms + 999, 1000)} s left"
  defp scan_words(_), do: "Passive (listens only)"

  defp battery_word(:live), do: "Live"
  defp battery_word(:stale), do: "Stale"
  defp battery_word(:connecting), do: "Connecting"
  defp battery_word(_), do: "Not heard"

  # 100%, 0 W out, 231 h left, 25 °C; how old, once it is not live; and
  # which one it is until there is a reading
  defp battery_detail(%{reading: nil} = b, _now), do: Enum.join(Enum.reject([b.name, b.address], &is_nil/1), ", ")

  defp battery_detail(%{reading: r} = b, now) do
    [
      r.charge && "#{r.charge}%",
      r.watts_out && "#{r.watts_out} W out",
      r.watts_in not in [nil, 0] && "#{r.watts_in} W in",
      hours_left(r),
      r.temp_c && "#{r.temp_c} °C",
      b.state != :live && "#{age(now - r.at)} ago"
    ]
    |> Enum.filter(& &1)
    |> Enum.join(", ")
  end

  defp hours_left(%{time_left_h: h} = r) when is_number(h) and h > 0 do
    shown = if h >= 10, do: round(h), else: Float.round(h * 1.0, 1)
    if (r.watts_in || 0) > (r.watts_out || 0), do: "#{shown} h to full", else: "#{shown} h left"
  end

  defp hours_left(_), do: nil

  defp age(ms) when ms < 120_000, do: "#{div(ms, 1000)} s"
  defp age(ms) when ms < 7_200_000, do: "#{div(ms, 60_000)} min"
  defp age(ms), do: "#{div(ms, 3_600_000)} h"

  defp detail(d) do
    [
      d.name && d.address,
      if(d.random, do: "random address"),
      Enum.map(d.manufacturer, fn {id, hex} -> "maker #{id}: #{String.slice(hex, 0, 24)}" end),
      Enum.map(d.service, fn {uuid, hex} -> "service #{uuid}: #{String.slice(hex, 0, 24)}" end),
      if(d.uuids != [], do: "services " <> Enum.join(d.uuids, " "))
    ]
    |> List.flatten()
    |> Enum.reject(&(&1 in [nil, false]))
    |> Enum.join(", ")
  end

  # -100 dBm is nothing, -40 dBm is right next to it
  defp percent(rssi), do: rssi |> Kernel.+(100) |> Kernel.*(100) |> div(60) |> max(0) |> min(100)
end
