defmodule Controller.MountLive do
  @moduledoc """
  The hand controller. Phone-first: a D-pad you press and hold, a rate picker,
  a big STOP. Talks to whichever mounts the cluster knows about, live.
  """
  use Controller, :live_view

  @rates [1, 8, 64, 400, 800]
  @rescan_ms 3_000

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket), do: send(self(), :rescan)

    {:ok,
     socket
     |> assign(rate: 64, goto_deg: "5", notice: nil, night: Controller.Settings.get("night", false), mounts: %{}, refs: %{})
     |> assign(selected: params["id"])
     |> rescan()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    {:noreply, assign(socket, selected: params["id"] || socket.assigns.selected || first_id(socket))}
  end

  # -- live updates -------------------------------------------------------------

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, @rescan_ms)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    {:noreply, assign(socket, mounts: Map.put(socket.assigns.mounts, snap.id, snap))}
  end

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})

    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id) do
      Mount.subscribe(ref)
    end

    mounts =
      for {id, ref} <- refs, into: %{} do
        {id, socket.assigns.mounts[id] || safe_snapshot(ref)}
      end

    socket = assign(socket, refs: refs, mounts: mounts)
    if socket.assigns.selected in Map.keys(refs), do: socket, else: assign(socket, selected: first_id(socket))
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Enum.sort() |> List.first()

  defp safe_snapshot(ref) do
    try do
      Mount.snapshot(ref)
    catch
      _, _ -> %{id: ref.id, node: ref.node, connected: false, axes: %{}, tracking: :off, homed: false}
    end
  end

  # -- events -----------------------------------------------------------------------

  @impl true
  def handle_event("select", %{"id" => id}, socket) do
    {:noreply, push_patch(socket, to: ~p"/#{id}")}
  end

  def handle_event("rate", %{"rate" => r}, socket) do
    {:noreply, assign(socket, rate: String.to_integer(r))}
  end

  def handle_event("hold", %{"axis" => axis, "dir" => dir}, socket) do
    rate = socket.assigns.rate * if(dir == "+", do: 1, else: -1)
    {:noreply, run(socket, &Mount.slew(&1, String.to_existing_atom(axis), rate, hold: true))}
  end

  def handle_event("release", %{"axis" => axis}, socket) do
    axis = String.to_existing_atom(axis)
    snap = current(socket)

    # Letting go of an RA nudge while tracking should go back to tracking, not stop.
    if axis == :ra and snap && snap.tracking != :off do
      {:noreply, run(socket, &Mount.track(&1, snap.tracking))}
    else
      {:noreply, run(socket, &Mount.stop(&1, axis))}
    end
  end

  def handle_event("key", %{"key" => key, "type" => type}, socket) do
    case {key, type} do
      {"ArrowUp", "down"} -> handle_event("hold", %{"axis" => "dec", "dir" => "+"}, socket)
      {"ArrowDown", "down"} -> handle_event("hold", %{"axis" => "dec", "dir" => "-"}, socket)
      {"ArrowRight", "down"} -> handle_event("hold", %{"axis" => "ra", "dir" => "+"}, socket)
      {"ArrowLeft", "down"} -> handle_event("hold", %{"axis" => "ra", "dir" => "-"}, socket)
      {k, "up"} when k in ["ArrowUp", "ArrowDown"] -> handle_event("release", %{"axis" => "dec"}, socket)
      {k, "up"} when k in ["ArrowLeft", "ArrowRight"] -> handle_event("release", %{"axis" => "ra"}, socket)
      {" ", "down"} -> handle_event("stop", %{}, socket)
      _ -> {:noreply, socket}
    end
  end

  def handle_event("stop", _, socket), do: {:noreply, run(socket, &Mount.stop/1)}
  def handle_event("estop", _, socket), do: {:noreply, run(socket, &Mount.emergency_stop/1)}
  def handle_event("home", _, socket), do: {:noreply, run(socket, &Mount.set_home/1)}

  def handle_event("track", %{"mode" => mode}, socket) do
    {:noreply, run(socket, &Mount.track(&1, String.to_existing_atom(mode)))}
  end

  def handle_event("goto", %{"axis" => axis, "sign" => sign, "deg" => deg}, socket) do
    case Float.parse(deg) do
      {d, _} ->
        d = if sign == "-", do: -d, else: d
        {:noreply, socket |> assign(goto_deg: deg) |> run(&Mount.goto_relative(&1, String.to_existing_atom(axis), d))}

      :error ->
        {:noreply, assign(socket, notice: "degrees?")}
    end
  end

  def handle_event("night", _, socket) do
    night = !socket.assigns.night
    Controller.Settings.put("night", night)
    {:noreply, assign(socket, night: night)}
  end
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        assign(socket, notice: "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> assign(socket, notice: nil)
            {:error, :limit} -> assign(socket, notice: "soft limit")
            {:error, :not_connected} -> assign(socket, notice: "mount not connected")
            {:error, other} -> assign(socket, notice: inspect(other))
          end
        catch
          :exit, _ -> assign(socket, notice: "mount unreachable")
        end
    end
  end

  defp current(socket), do: socket.assigns.mounts[socket.assigns.selected]

  # -- render -----------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, snap: current(%{assigns: assigns}), rates: @rates)

    ~H"""
    <main class={["pad", @night && "night"]} id="pad" phx-hook="Keys">
      <header>
        <form :if={map_size(@refs) > 1} phx-change="select">
          <select name="id">
            <option :for={id <- Enum.sort(Map.keys(@refs))} value={id} selected={id == @selected}>{id}</option>
          </select>
        </form>
        <h1 :if={map_size(@refs) <= 1}>{@selected || "no mount"}</h1>
        <span>
          <.link navigate={if @selected, do: ~p"/sky/#{@selected}", else: ~p"/sky"} class="ghost">✦ sky</.link>
          <button class="ghost" phx-click="night" aria-label="night mode">◐</button>
        </span>
      </header>

      <%= if @snap && @snap.connected do %>
        <section class="readout">
          <div class="axis">
            <span class="label">RA</span>
            <span class="deg">{fmt(@snap.axes.ra.degrees)}</span>
            <span class={["dot", @snap.axes.ra.running && "on"]}></span>
          </div>
          <div class="axis">
            <span class="label">DEC</span>
            <span class="deg">{fmt(@snap.axes.dec.degrees)}</span>
            <span class={["dot", @snap.axes.dec.running && "on"]}></span>
          </div>
          <div class="status">
            <span :if={@snap.tracking != :off} class="badge on">tracking {@snap.tracking}</span>
            <span :if={@snap.tracking == :off} class="badge">not tracking</span>
            <span class={["badge", @snap.homed && "on"]}>{if @snap.homed, do: "homed · limits on", else: "not homed"}</span>
            <span :if={@snap.node != :nonode@nohost} class="badge dim">{@snap.node}</span>
          </div>
        </section>

        <section class="dpad">
          <span></span>
          <button class="arrow" id="dec-up" phx-hook="Hold" data-axis="dec" data-dir="+">▲<small>Dec +</small></button>
          <span></span>
          <button class="arrow" id="ra-left" phx-hook="Hold" data-axis="ra" data-dir="-">◀<small>RA −</small></button>
          <button class="stop" phx-click="stop">STOP</button>
          <button class="arrow" id="ra-right" phx-hook="Hold" data-axis="ra" data-dir="+">▶<small>RA +</small></button>
          <span></span>
          <button class="arrow" id="dec-down" phx-hook="Hold" data-axis="dec" data-dir="-">▼<small>Dec −</small></button>
          <span></span>
        </section>

        <section class="rates">
          <button :for={r <- @rates} class={["rate", r == @rate && "on"]} phx-click="rate" phx-value-rate={r}>
            {r}×
          </button>
        </section>

        <section class="row">
          <button :if={@snap.tracking == :off} phx-click="track" phx-value-mode="sidereal">Track ☆</button>
          <button :if={@snap.tracking != :off} class="on" phx-click="track" phx-value-mode="off">Tracking ☆</button>
          <button phx-click="home" data-confirm="Set the current position as home (counterweight down, scope at the pole)?">Set home</button>
        </section>

        <section class="goto">
          <form phx-submit="goto" class="row">
            <input type="hidden" name="axis" value="ra" /><input type="hidden" name="sign" value="+" />
            <input name="deg" inputmode="decimal" value={@goto_deg} aria-label="degrees" />
            <button>RA +</button>
          </form>
          <div class="row">
            <button phx-click="goto" phx-value-axis="ra" phx-value-sign="-" phx-value-deg={@goto_deg}>RA −</button>
            <button phx-click="goto" phx-value-axis="dec" phx-value-sign="+" phx-value-deg={@goto_deg}>Dec +</button>
            <button phx-click="goto" phx-value-axis="dec" phx-value-sign="-" phx-value-deg={@goto_deg}>Dec −</button>
          </div>
        </section>

        <button class="estop" phx-click="estop">EMERGENCY STOP</button>
      <% else %>
        <section class="empty">
          <p :if={@snap}>{@selected}: not connected<span :if={@snap[:error]}> — {inspect(@snap.error)}</span></p>
          <p :if={!@snap}>No mount found. Plug the EQDIR cable into this machine, or connect to a node that has one.</p>
        </section>
      <% end %>

      <p :if={@notice} class="notice" phx-click="dismiss">{@notice}</p>
    </main>
    """
  end

  defp fmt(deg) when is_number(deg) do
    sign = if deg < 0, do: "−", else: "+"
    d = abs(deg)
    whole = trunc(d)
    min = (d - whole) * 60
    "#{sign}#{whole}° #{:erlang.float_to_binary(min * 1.0, decimals: 1)}′"
  end

  defp fmt(_), do: "—"
end
