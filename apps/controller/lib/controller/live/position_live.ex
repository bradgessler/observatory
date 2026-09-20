defmodule Controller.PositionLive do
  @moduledoc """
  Position: the put-it-back tool. Type an axis angle (degrees from home) and
  go there; or go home. Shows where each axis is, live.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

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
       ra_target: "0",
       dec_target: "0",
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

    assign(socket, refs: refs, selected: selected, snap: snap, page_title: "#{selected || "no mount"} · Position")
  end

  @impl true
  def handle_event("targets", %{"ra" => ra, "dec" => dec}, socket), do: {:noreply, assign(socket, ra_target: ra, dec_target: dec)}

  # Absolute = relative from where we are; the driver only knows relative moves.
  def handle_event("go", %{"axis" => axis}, socket) do
    axis = String.to_existing_atom(axis)
    target = if axis == :ra, do: socket.assigns.ra_target, else: socket.assigns.dec_target

    with %{axes: axes} <- socket.assigns.snap, {t, _} <- Float.parse(target) do
      {:noreply, run(socket, &Mount.goto_relative(&1, axis, t - axes[axis].degrees))}
    else
      nil -> {:noreply, assign(socket, notice: "no mount")}
      _ -> {:noreply, assign(socket, notice: "#{String.upcase(to_string(axis))} target must be a number of degrees, like 12.5 or -30")}
    end
  end

  def handle_event("home", _, socket) do
    with %{axes: axes} <- socket.assigns.snap do
      socket = run(socket, &Mount.goto_relative(&1, :ra, -axes.ra.degrees))
      {:noreply, run(socket, &Mount.goto_relative(&1, :dec, -axes.dec.degrees))}
    else
      _ -> {:noreply, assign(socket, notice: "no mount")}
    end
  end

  def handle_event("stop", _, socket), do: {:noreply, run(socket, &Mount.stop/1)}
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
    ~H"""
    <.page id="position" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Start" />
        <.title>{@selected} · Position</.title>
        <.actions><.help href={~p"/docs/position"} label="position" /></.actions>
      </:header>

      <.card title="Axes, Degrees From Zero">
        <%!-- typing only stores the target; Go is a separate key (3.2.2) --%>
        <form phx-change="targets" class="pos-grid" aria-label="axis targets">
          <label for="pos-ra" class="pos-k">RA</label>
          <span class="pos-now" aria-label="RA now">{if @snap && @snap.axes[:ra], do: fmt(@snap.axes.ra.degrees), else: "—"}</span>
          <input id="pos-ra" name="ra" type="text" inputmode="decimal" autocomplete="off" value={@ra_target} class="field" aria-label="RA target, degrees from zero" />
          <.btn type="button" phx-click="go" phx-value-axis="ra" aria-label="Go to the RA target">Go</.btn>

          <label for="pos-dec" class="pos-k">Dec</label>
          <span class="pos-now" aria-label="Dec now">{if @snap && @snap.axes[:dec], do: fmt(@snap.axes.dec.degrees), else: "—"}</span>
          <input id="pos-dec" name="dec" type="text" inputmode="decimal" autocomplete="off" value={@dec_target} class="field" aria-label="Dec target, degrees from zero" />
          <.btn type="button" phx-click="go" phx-value-axis="dec" aria-label="Go to the Dec target">Go</.btn>
        </form>
        <.row>
          <.btn variant="primary" phx-click="home" data-confirm="Move both axes back to 0°?">Back to zero (0°, 0°)</.btn>
          <.btn :if={!@nested} phx-click="stop">Stop</.btn>
        </.row>
        <.hint>Zero is where the axes were zeroed: counterweight down, tube along the polar axis, if that's how the mount stood. Moves are full speed with the mount's own ramps; soft limits apply once zeroed.</.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp fmt(d), do: "#{if d < 0, do: "−", else: "+"}#{:erlang.float_to_binary(abs(d) * 1.0, decimals: 2)}°"
end
