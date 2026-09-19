defmodule Controller.TiltLive do
  @moduledoc """
  Tilt: eyepiece mode. Hold the one big button (the dead-man) and tilt the
  phone; the mount follows, faster the further you tilt. Let go and it stops.
  Meant for the moment your eye is on the eyepiece and your thumb is all you
  have. The phone's orientation sensor is read in the browser (there is no
  other way to read it) and forwarded as a plain vector; the server does
  everything else.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @rates [1, 8, 64, 400]

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       refs: %{},
       selected: params["id"] || session["id"],
       snap: nil,
       rate: 8,
       held: [],
       vec: nil,
       sensor: :unknown,
       notice: nil
     )
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()

    snap =
      if ref = refs[selected] do
        try do
          Mount.snapshot(ref)
        catch
          _, _ -> nil
        end
      end

    assign(socket, refs: refs, selected: selected, snap: snap)
  end

  # -- events -------------------------------------------------------------------------
  # The Tilt hook sends "tilt" {x, y, mag} every 250 ms while the button is
  # held (x right, y up, mag 0..1 past the null zone) and "tilt_end" on
  # release, page hide, or sensor loss. "sensor" reports availability.

  @impl true
  def handle_event("rate", %{"rate" => r}, socket), do: {:noreply, assign(socket, rate: String.to_integer(r))}

  def handle_event("sensor", %{"state" => st}, socket) do
    sensor = Map.get(%{"ok" => :ok, "denied" => :denied, "none" => :none, "insecure" => :insecure}, st, :unknown)
    {:noreply, assign(socket, sensor: sensor)}
  end

  def handle_event("tilt", %{"x" => x, "y" => y, "mag" => mag}, socket) when is_number(mag) do
    if mag <= 0 do
      handle_event("tilt_end", %{}, assign(socket, vec: {x, y, mag}))
    else
      ctx = Controller.Sky.Pointing.context()
      rates = Controller.Sky.Joystick.compass_vector(socket.assigns.snap, ctx, {x / 1, y / 1}, socket.assigns.rate * mag)
      socket = Enum.reduce(rates, socket, fn {axis, r}, s -> run(s, &Mount.slew(&1, axis, r, hold: true)) end)
      # anything held a moment ago but not now must stop
      socket = Enum.reduce(socket.assigns.held -- Enum.map(rates, &elem(&1, 0)), socket, &release(&2, &1))
      {:noreply, assign(socket, held: Enum.map(rates, &elem(&1, 0)), vec: {x, y, mag})}
    end
  end

  def handle_event("tilt_end", _, socket) do
    socket = Enum.reduce(socket.assigns.held, socket, &release(&2, &1))
    {:noreply, assign(socket, held: [], vec: nil)}
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp release(socket, axis) do
    snap = socket.assigns.snap

    if axis == :ra and snap && snap.tracking != :off,
      do: run(socket, &Mount.track(&1, snap.tracking)),
      else: run(socket, &Mount.stop(&1, axis, instant: true))
  end

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> socket
            {:error, :limit} -> assign(socket, notice: "soft limit")
            {:error, e} -> assign(socket, notice: inspect(e))
          end
        catch
          :exit, _ -> assign(socket, notice: "mount unreachable")
        end
    end
  end

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, rates: @rates)

    ~H"""
    <.page id="tilt" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/tilt?#{[mount: @selected]}"} label="bench" />
        <.title>{@selected} · tilt</.title>
        <.actions><.help href={~p"/docs/keypad"} /></.actions>
      </:header>

      <section class="tilt-wrap">
        <button id="tilt-pad" class={["tilt-pad", @held != [] && "live"]} phx-hook="Tilt" aria-label="hold and tilt the phone to move">
          <span class="tilt-dot" data-dot></span>
          <b>{if @held == [], do: "hold", else: "moving"}</b>
          <small>{tilt_words(@vec)}</small>
        </button>
      </section>

      <section class="rates rates-4">
        <button :for={r <- @rates} class={["rate", r == @rate && "on"]} phx-click="rate" phx-value-rate={r}>{r}×</button>
      </section>

      <.hint :if={@sensor == :ok}>Hold the button. The way you hold the phone at that moment is "still"; tilt away from it to move, more tilt is faster (up to {@rate}×). Let go: it stops.</.hint>
      <.hint :if={@sensor == :unknown}>Hold the button once to ask the phone for its tilt sensor.</.hint>
      <.hint :if={@sensor == :denied}>The phone said no to the tilt sensor. On iPhone that prompt appears once; Settings › Safari › Motion &amp; Orientation Access turns it back on.</.hint>
      <.hint :if={@sensor == :insecure}>Tilt needs HTTPS — the browser only exposes the orientation sensor on a secure page. Open this over the tunnel URL (Devices shows it).</.hint>
      <.hint :if={@sensor == :none}>No orientation sensor here. This surface is for a phone in the hand; on a laptop use the keypad or nudge.</.hint>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </.page>
    """
  end

  defp tilt_words(nil), do: "tilt sensor idle"
  defp tilt_words({_, _, mag}) when mag <= 0, do: "level · in the null zone"

  defp tilt_words({x, y, mag}) do
    dir =
      cond do
        abs(y) >= abs(x) and y > 0 -> "toward pole"
        abs(y) >= abs(x) -> "away from pole"
        x > 0 -> "west"
        true -> "east"
      end

    "#{dir} · #{round(mag * 100)}%"
  end
end
