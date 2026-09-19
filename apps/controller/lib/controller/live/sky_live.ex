defmodule Controller.SkyLive do
  @moduledoc """
  An all-sky map for right now, from the configured site. Tap an object and
  the selected mount goes there.

  Pointing is a first-order model and is flagged as such in the UI: it assumes
  the mount was homed at the pole with the counterweight down, and uses the
  axis signs in `config :controller, :pointing`. Plate solving replaces this.
  """
  use Controller, :live_view

  alias Controller.Sky.{Astro, Stars}

  @tick_ms 10_000

  @impl true
  def mount(params, _session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      :timer.send_interval(@tick_ms, :tick)
    end

    site = Application.get_env(:controller, :site, %{lat: 0.0, lon: 0.0, name: "nowhere"})
    pointing = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    {:ok,
     socket
     |> assign(site: site, pointing: pointing, now: DateTime.utc_now(), refs: %{}, snap: nil,
       selected: params["id"], target: nil, notice: nil)
     |> rescan()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    {:noreply, assign(socket, selected: params["id"] || socket.assigns.selected || first_id(socket))}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, assign(socket, now: DateTime.utc_now())}

  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected,
      do: {:noreply, assign(socket, snap: snap)},
      else: {:noreply, socket}
  end

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    socket = assign(socket, refs: refs)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: first_id(socket)
    snap = if ref = refs[selected], do: safe_snapshot(ref)
    assign(socket, selected: selected, snap: snap)
  end

  defp first_id(socket), do: socket.assigns.refs |> Map.keys() |> Enum.sort() |> List.first()

  defp safe_snapshot(ref) do
    try do
      Mount.snapshot(ref)
    catch
      _, _ -> nil
    end
  end

  # -- events -----------------------------------------------------------------------

  @impl true
  def handle_event("pick", %{"id" => id}, socket) do
    {:noreply, assign(socket, target: Stars.get(id), notice: nil)}
  end

  def handle_event("clear", _, socket), do: {:noreply, assign(socket, target: nil)}

  def handle_event("goto", _, %{assigns: %{target: t, snap: snap}} = socket) when not is_nil(t) do
    cond do
      is_nil(snap) or not snap.connected ->
        {:noreply, assign(socket, notice: "no mount connected")}

      not snap.homed ->
        {:noreply, assign(socket, notice: "set home on the keypad first (counterweight down, scope at the pole)")}

      true ->
        {ra_axis, dec_axis} = axes_for(t, socket.assigns)
        ref = socket.assigns.refs[socket.assigns.selected]
        d_ra = ra_axis - snap.axes.ra.degrees
        d_dec = dec_axis - snap.axes.dec.degrees

        result =
          try do
            with :ok <- Mount.goto_relative(ref, :ra, d_ra),
                 :ok <- Mount.goto_relative(ref, :dec, d_dec),
                 do: :ok
          catch
            :exit, _ -> {:error, :unreachable}
          end

        notice =
          case result do
            :ok -> "slewing to #{t.name} (ΔRA #{fmt1(d_ra)}°, ΔDec #{fmt1(d_dec)}°)"
            {:error, :limit} -> "#{t.name} is outside the soft limits"
            {:error, e} -> inspect(e)
          end

        {:noreply, assign(socket, notice: notice)}
    end
  end

  def handle_event("goto", _, socket), do: {:noreply, socket}
  def handle_event("stop", _, socket) do
    if ref = socket.assigns.refs[socket.assigns.selected], do: Mount.stop(ref)
    {:noreply, assign(socket, notice: "stopped")}
  end

  # -- pointing model -----------------------------------------------------------------

  # Where the axes must be for an object right now (degrees from home).
  defp axes_for(obj, %{now: now, site: site, pointing: p}) do
    lst = Astro.lst_deg(now, site.lon)
    ha = Astro.hour_angle(lst, obj.ra_deg)
    {ha / p.ha_sign, (90 - obj.dec_deg) / p.dec_sign}
  end

  # Where the scope points now, from the axes (nil until homed).
  defp scope_radec(%{homed: true, axes: %{ra: ra, dec: dec}}, %{now: now, site: site, pointing: p}) do
    lst = Astro.lst_deg(now, site.lon)
    ha = ra.degrees * p.ha_sign
    {Astro.norm360(lst - ha), 90 - dec.degrees * p.dec_sign}
  end

  defp scope_radec(_, _), do: nil

  # -- render -------------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    lst = Astro.lst_deg(assigns.now, assigns.site.lon)

    objects =
      for o <- Stars.all(),
          {alt, az} = Astro.alt_az(o.ra_deg, o.dec_deg, assigns.site.lat, lst),
          alt > -2 do
        {x, y} = Astro.project(alt, az)
        Map.merge(o, %{alt: alt, az: az, x: x * 100, y: y * 100})
      end

    scope =
      case scope_radec(assigns.snap, assigns) do
        {ra, dec} ->
          {alt, az} = Astro.alt_az(ra, dec, assigns.site.lat, lst)
          {x, y} = Astro.project(max(alt, -5.0), az)
          %{x: x * 100, y: y * 100, alt: alt}

        nil ->
          nil
      end

    assigns = assign(assigns, objects: objects, scope: scope, lst: lst)

    ~H"""
    <main class="sky" id="sky">
      <header>
        <.link navigate={if @selected, do: ~p"/#{@selected}", else: ~p"/"} class="ghost">‹ keypad</.link>
        <h1>{@site[:name]} · {Calendar.strftime(@now, "%H:%M")} UTC · LST {fmt_h(@lst)}</h1>
      </header>

      <svg viewBox="-104 -104 208 208" class="map" phx-click="clear">
        <defs>
          <radialGradient id="dome" cx="50%" cy="50%" r="50%">
            <stop offset="70%" stop-color="var(--sky1)" /><stop offset="100%" stop-color="var(--sky2)" />
          </radialGradient>
        </defs>
        <circle r="100" fill="url(#dome)" stroke="var(--edge)" stroke-width=".6" />
        <circle :for={alt <- [30, 60]} r={100 * :math.tan((90 - alt) / 2 * :math.pi() / 180) / :math.tan(:math.pi() / 4)} fill="none" stroke="var(--edge)" stroke-width=".3" stroke-dasharray="1 2" />
        <line x1="-100" y1="0" x2="100" y2="0" stroke="var(--edge)" stroke-width=".3" />
        <line x1="0" y1="-100" x2="0" y2="100" stroke="var(--edge)" stroke-width=".3" />
        <text x="0" y="-101.5" class="card">N</text>
        <text x="0" y="103.5" class="card">S</text>
        <text x="-102" y="1" class="card" text-anchor="end">E</text>
        <text x="102" y="1" class="card" text-anchor="start">W</text>

        <g :for={o <- @objects} phx-click="pick" phx-value-id={o.id} class={["obj", o.kind, @target && @target.id == o.id && "picked"]}>
          <circle class="hit" cx={o.x} cy={o.y} r={radius(o) + 4} />
          <circle :if={o.kind == :star} cx={o.x} cy={o.y} r={radius(o)} />
          <rect :if={o.kind != :star} x={o.x - 1.6} y={o.y - 1.6} width="3.2" height="3.2" transform={"rotate(45 #{o.x} #{o.y})"} />
          <text :if={o.mag < 1.6 or o.kind != :star} x={o.x + 2.4} y={o.y + 1}>{short(o.name)}</text>
        </g>

        <g :if={@scope} class="scope" transform={"translate(#{@scope.x} #{@scope.y})"}>
          <circle r="5" fill="none" />
          <line x1="-8" y1="0" x2="-3" y2="0" /><line x1="3" y1="0" x2="8" y2="0" />
          <line x1="0" y1="-8" x2="0" y2="-3" /><line x1="0" y1="3" x2="0" y2="8" />
        </g>
      </svg>

      <section class="pick" :if={@target}>
        <div>
          <strong>{@target.name}</strong>
          <span class="dim">
            alt {fmt1(alt_of(@objects, @target))}° · az {fmt1(az_of(@objects, @target))}° · mag {@target.mag}
          </span>
        </div>
        <button class="go" phx-click="goto">Slew</button>
        <button phx-click="stop">Stop</button>
      </section>
      <section class="pick hint" :if={!@target}>
        <span class="dim">
          Tap an object to slew. <span :if={@snap && !@snap.homed}>Scope marker appears once you set home.</span>
          <span :if={!@snap}>No mount connected.</span>
        </span>
      </section>

      <p class="fine">Pointing model: homed at the pole, counterweight down; axis signs from config, unverified on sky. Plate solving will replace this (#10, #5).</p>
      <p :if={@notice} class="notice" phx-click="clear">{@notice}</p>
    </main>
    """
  end

  defp radius(%{kind: :star, mag: m}), do: max(0.6, 2.6 - m * 0.55)
  defp radius(_), do: 1.6

  defp short(name), do: name |> String.split(" ") |> List.first()

  defp alt_of(objects, t), do: (Enum.find(objects, &(&1.id == t.id)) || %{alt: 0}).alt
  defp az_of(objects, t), do: (Enum.find(objects, &(&1.id == t.id)) || %{az: 0}).az

  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)

  defp fmt_h(deg) do
    h = deg / 15
    "#{trunc(h)}h#{:erlang.float_to_binary((h - trunc(h)) * 60, decimals: 0) |> String.pad_leading(2, "0")}m"
  end
end
