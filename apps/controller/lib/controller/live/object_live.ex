defmodule Controller.ObjectLive do
  @moduledoc """
  One object: what it is, where it is right now, whether this scope will show
  it, and the buttons that matter — Slew, Search, Sync.
  """
  use Controller, :live_view

  alias Controller.Settings
  alias Controller.Sky.{Astro, Blurbs, Catalog, Ephemeris, Pointing}

  @spiral_step 0.4
  @spiral_pause_ms 2_500

  @impl true
  def mount(%{"id" => id} = params, _session, socket) do
    now = DateTime.utc_now()
    obj = Catalog.object(id) || Enum.find(Ephemeris.objects(now), &(&1.id == id))

    if connected?(socket) do
      send(self(), :rescan)
      :timer.send_interval(15_000, :tick)
      Settings.subscribe()
    end

    {:ok,
     socket
     |> assign(id: id, obj: obj, now: now, refs: %{}, snap: nil, selected: params["mount"], notice: nil,
       search: nil, night: Settings.get("night", false), aperture: Settings.get("aperture_mm", 100))
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, socket |> assign(now: DateTime.utc_now()) |> compute()}

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _key, _v}, socket), do: {:noreply, socket |> assign(aperture: Settings.get("aperture_mm", 100)) |> compute()}

  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 5_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info(:search_step, %{assigns: %{search: nil}} = socket), do: {:noreply, socket}

  def handle_info(:search_step, %{assigns: %{search: %{steps: steps, n: n}}} = socket) do
    case Enum.at(steps, n) do
      nil ->
        {:noreply, assign(socket, search: nil, notice: "search finished")}

      {dra, ddec} ->
        ref = socket.assigns.refs[socket.assigns.selected]
        safe(fn -> if dra != 0, do: Mount.goto_relative(ref, :ra, dra * @spiral_step) end)
        safe(fn -> if ddec != 0, do: Mount.goto_relative(ref, :dec, ddec * @spiral_step) end)
        Process.send_after(self(), :search_step, @spiral_pause_ms)
        {:noreply, assign(socket, search: %{steps: steps, n: n + 1})}
    end
  end

  defp rescan(socket) do
    refs = Map.new(Mount.list(), &{&1.id, &1})
    for {id, ref} <- refs, not Map.has_key?(socket.assigns.refs, id), do: Mount.subscribe(ref)
    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Enum.sort() |> List.first()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)
    assign(socket, refs: refs, selected: selected, snap: if(is_map(snap), do: snap))
  end

  # Where it is now and whether it's on tonight's list (which carries the plain-words verdict).
  defp compute(%{assigns: %{obj: nil}} = socket), do: socket

  defp compute(socket) do
    %{obj: obj, now: now} = socket.assigns
    ctx = Pointing.context(now)
    lst = Astro.lst_deg(now, ctx.site.lon)
    {alt, az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, ctx.site.lat, lst)
    horizon = Settings.horizon()
    tree = Settings.horizon_at(horizon, az)
    ranked = Controller.SkyLive.targets(now, ctx.site, horizon, socket.assigns.aperture)
    entry = Enum.find(ranked, &(&1.id == obj.id))
    rank = entry && Enum.find_index(ranked, &(&1.id == obj.id)) + 1

    assign(socket,
      ctx: ctx,
      alt: alt,
      az: az,
      tree: tree,
      entry: entry,
      rank: rank,
      visible: alt > tree,
      scope: Pointing.scope_radec(socket.assigns.snap, ctx)
    )
  end

  # -- events -----------------------------------------------------------------------

  @impl true
  def handle_event("slew", _, %{assigns: %{obj: obj, snap: snap}} = socket) do
    ref = socket.assigns.refs[socket.assigns.selected]

    notice =
      case Pointing.slew(ref, snap, obj, socket.assigns.ctx, track: Settings.get("auto_track", true)) do
        {:ok, d_ra, d_dec} -> "slewing (ΔRA #{fmt1(d_ra)}°, ΔDec #{fmt1(d_dec)}°)"
        {:error, :not_connected} -> "no mount connected"
        {:error, :not_homed} -> "set home on the keypad first"
        {:error, :limit} -> "outside the soft limits"
        {:error, e} -> inspect(e)
      end

    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("stop", _, socket) do
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.stop(ref) end)
    {:noreply, assign(socket, notice: "stopped", search: nil)}
  end

  def handle_event("sync", _, %{assigns: %{obj: obj, snap: snap}} = socket) do
    if snap && snap.homed do
      st = Pointing.sync(snap, obj, socket.assigns.ctx)
      {:noreply, socket |> assign(notice: "lined up on #{obj.name} · #{st.n} star#{if st.n == 1, do: "", else: "s"} · agree to #{fmt1(st.rms_arcmin || 0.0)}′") |> compute()}
    else
      {:noreply, assign(socket, notice: "zero the axes first (Setup)")}
    end
  end

  def handle_event("search", _, socket) do
    if socket.assigns.search do
      {:noreply, socket}
    else
      Process.send_after(self(), :search_step, @spiral_pause_ms)
      {:noreply, assign(socket, search: %{steps: spiral(), n: 0}, notice: "searching… Stop when you see it")}
    end
  end

  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp spiral do
    dirs = [{1, 0}, {0, 1}, {-1, 0}, {0, -1}]

    Stream.iterate({0, 1}, fn {i, len} -> {i + 1, if(rem(i, 2) == 1, do: len + 1, else: len)} end)
    |> Stream.flat_map(fn {i, len} -> List.duplicate(Enum.at(dirs, rem(i, 4)), len) end)
    |> Enum.take(48)
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(%{obj: nil} = assigns) do
    ~H"""
    <main class={["object", @night && "night"]}>
      <header><.link navigate={~p"/sky"} class="ghost">‹ sky</.link></header>
      <p class="empty">Nothing called "{@id}" in the catalog.</p>
    </main>
    """
  end

  def render(assigns) do
    ~H"""
    <main class={["object", @night && "night"]}>
      <header>
        <.link navigate={if @selected, do: ~p"/sky/#{@selected}", else: ~p"/sky"} class="ghost">‹ sky</.link>
        <span class="hdr-actions">
          <button class="stop-mini" phx-click="stop">STOP</button>
        </span>
      </header>

      <section class="card">
        <h1>{@obj.name}</h1>
        <p class="kind">{kind_name(@obj.kind)}<span :if={@obj[:desig]}> · {@obj.desig}</span><span :if={@rank}> · #{@rank} tonight</span></p>
        <p class="blurb">{Blurbs.for(@obj)}</p>
      </section>

      <section class="card facts">
        <div><span class="k">now</span><span class="v">{if @alt > 0, do: "#{fmt0(@alt)}° up, #{compass(@az)}", else: "below the horizon"}</span></div>
        <div><span class="k">you'll see</span><span class="v">{verdict(assigns)}</span></div>
        <div :if={@entry}><span class="k">window</span><span class="v">{when_text(@entry.status)}</span></div>
        <div><span class="k">brightness</span><span class="v">mag {@obj.mag} <.link href={~p"/docs/magnitude"} class="help">?</.link></span></div>
      </section>

      <section class="actions">
        <button class="go big" phx-click="slew" disabled={!@snap || !@snap.connected}>Slew</button>
        <div class="row">
          <button :if={!@search} phx-click="search" disabled={!@snap || !@snap.connected}>Search</button>
          <button :if={@search} class="on" phx-click="stop">Stop search</button>
          <button phx-click="sync" disabled={!@snap || !@snap.homed}>Sync</button>
        </div>
        <p :if={@snap && !@snap.homed} class="horizon-hint">Set home on the keypad before slewing.</p>
        <p :if={!@snap} class="horizon-hint">No mount connected.</p>
      </section>

      <p :if={@notice} id={"notice-#{:erlang.phash2(@notice)}"} class="notice">{@notice}</p>
    </main>
    """
  end

  defp verdict(%{visible: false, alt: alt, tree: tree}) when alt > 0, do: "behind your tree line (#{fmt0(alt)}° up, trees to #{tree}°)"
  defp verdict(%{visible: false}), do: "not up right now"
  defp verdict(%{entry: %{words: w}}), do: w
  defp verdict(_), do: "faint for this scope tonight"

  defp kind_name(:moon), do: "the Moon"
  defp kind_name(:planet), do: "planet"
  defp kind_name(:star), do: "star"
  defp kind_name(:cluster), do: "star cluster"
  defp kind_name(:galaxy), do: "galaxy"
  defp kind_name(:nebula), do: "nebula"
  defp kind_name(:planetary), do: "planetary nebula"
  defp kind_name(k), do: to_string(k)

  defp when_text(:good), do: "up for 2h+"
  defp when_text(:sets_later), do: "sets within 2h"
  defp when_text(:sets_soon), do: "sets within the hour — look now"
  defp when_text(:rising), do: "rises within 2h"

  defp compass(az), do: Enum.at(~w(N NE E SE S SW W NW), round(Astro.norm360(az) / 45) |> rem(8))
  defp fmt1(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt0(x), do: :erlang.float_to_binary(x * 1.0, decimals: 0)
end
