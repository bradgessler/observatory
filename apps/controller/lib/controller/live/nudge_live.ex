defmodule Controller.NudgeLive do
  @moduledoc """
  Nudge: tap to move an exact step. No holding, no rates — pick a step
  (1′, 5′, 30′, 2°) and each tap is one goto of that size on one axis. The
  deterministic tool for centering something in an eyepiece.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @steps [{"1′", 1 / 60}, {"5′", 5 / 60}, {"30′", 0.5}, {"2°", 2.0}]

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
       step: 5 / 60,
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

  @impl true
  def handle_event("step", %{"deg" => d}, socket) do
    {f, _} = Float.parse(d)
    {:noreply, assign(socket, step: f)}
  end

  # Compass convention through the calibrated axis signs, same as the keypad.
  def handle_event("nudge", %{"dir" => dir}, socket) do
    ctx = Controller.Sky.Pointing.context()
    vec = %{"up" => {0.0, 1.0}, "down" => {0.0, -1.0}, "left" => {-1.0, 0.0}, "right" => {1.0, 0.0}}[dir]

    case Controller.Sky.Joystick.compass_vector(socket.assigns.snap, ctx, vec, 1.0) do
      [{axis, sign}] ->
        {:noreply, run(socket, &Mount.goto_relative(&1, axis, sign * socket.assigns.step))}

      _ ->
        {:noreply, socket}
    end
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

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

  @impl true
  def render(assigns) do
    assigns = assign(assigns, steps: @steps)

    ~H"""
    <.page id="nudge" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/bench/nudge?#{[mount: @selected]}"} label="Bench" />
        <.title>{@selected} · Nudge</.title>
        <.actions><.help href={~p"/docs/keypad"} /></.actions>
      </:header>

      <section class="dpad">
        <span></span>
        <button class="arrow" phx-click="nudge" phx-value-dir="up">▲<small>toward pole</small></button>
        <span></span>
        <button class="arrow" phx-click="nudge" phx-value-dir="left">◀<small>E</small></button>
        <span class="dpad-centre"><b>{step_label(@step, @steps)}</b><small>per tap</small></span>
        <button class="arrow" phx-click="nudge" phx-value-dir="right">▶<small>W</small></button>
        <span></span>
        <button class="arrow" phx-click="nudge" phx-value-dir="down">▼<small>away</small></button>
        <span></span>
      </section>

      <section class="rates rates-4">
        <button :for={{lbl, deg} <- @steps} class={["rate", abs(deg - @step) < 1.0e-6 && "on"]} phx-click="step" phx-value-deg={deg}>{lbl}</button>
      </section>

      <.hint>Each tap moves exactly one step, at full speed with the mount's own ramps. Nothing to hold.</.hint>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp step_label(step, steps) do
    case Enum.find(steps, fn {_, d} -> abs(d - step) < 1.0e-6 end) do
      {lbl, _} -> lbl
      nil -> "#{step}°"
    end
  end
end
