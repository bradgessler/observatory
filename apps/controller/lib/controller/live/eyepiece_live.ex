defmodule Controller.EyepieceLive do
  @moduledoc """
  What the tube sees: the star field where it is really pointing, drawn.

  On a simulator this is the honest answer, taken from the hidden truth
  geometry (`Controller.Sim.Truth`), so a mount set down badly shows the star
  off-centre and you have to nudge it in, exactly as outside. On a real mount
  there is nothing to see through a browser, so it draws the software's
  belief and says which it is.

  Untracked, the field drifts west because the sky moves and the encoders do
  not. Tracking holds it. Nudging moves it. All from the 250 ms snapshot.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Catalog, Ephemeris, Lineup, Pointing, Tracker}

  # A real eyepiece is half a degree wide, but the catalogue stops at
  # magnitude 6 (0.12 stars per square degree), so a half-degree field is
  # empty most places you point. These widths show something honest instead
  # of inventing stars that are not there.
  @fovs [2.0, 5.0, 10.0, 20.0]
  @steps [1.0 / 60, 5.0 / 60, 0.5]
  @r 100.0

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      Telescope.subscribe("tracker")
    end

    params = if is_map(params), do: params, else: %{}

    {:ok,
     socket
     |> assign(
       page_title: "Eyepiece",
       night: Settings.get("night", false),
       nested: session["nested"] == true,
       selected: params["id"] || session["id"] || session["telescope"],
       refs: %{},
       subscribed: MapSet.new(),
       snap: nil,
       tracker: nil,
       fov: Settings.get("eyepiece_fov_deg", 5.0) / 1,
       step: 5.0 / 60,
       notice: nil,
       fovs: @fovs,
       steps: @steps,
       r_field: @r
     )
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> compute()}
  end

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, compute(assign(socket, snap: snap))}, else: {:noreply, socket}
  end

  def handle_info({:tracker, id, status}, socket) do
    if id == socket.assigns.selected, do: {:noreply, compute(assign(socket, tracker: status))}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, compute(socket)}

  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    selected = if socket.assigns.selected in Map.keys(refs), do: socket.assigns.selected, else: refs |> Map.keys() |> Mount.default()
    snap = if ref = refs[selected], do: safe(fn -> Mount.snapshot(ref) end)
    assign(socket, refs: refs, subscribed: subscribed, selected: selected, snap: if(is_map(snap), do: snap), page_title: Controller.Words.title(selected, "Eyepiece"))
  end

  defp compute(%{assigns: %{selected: nil}} = socket),
    do: assign(socket, centre: nil, objects: [], target: nil, target_off: nil, next_star: nil)

  defp compute(socket) do
    id = socket.assigns.selected
    now = DateTime.utc_now()
    ctx = Pointing.context(now, id)
    tracker = socket.assigns.tracker || Tracker.status(id)
    centre = socket.assigns.snap && Truth.looking_at(socket.assigns.snap, ctx)

    target =
      cond do
        tracker && tracker[:target] && tracker.target[:ra_deg] -> Map.put(tracker.target, :name, tracker.name)
        true -> nil
      end

    assign(socket,
      now: now,
      ctx: ctx,
      tracker: tracker,
      centre: centre,
      target: target,
      objects: objects_near(centre, socket.assigns.fov, now),
      target_off: off_field(centre, target, socket.assigns.fov),
      next_star: next_star(id, ctx)
    )
  end

  # -- what is in the field --------------------------------------------------------------

  defp objects_near(nil, _fov, _now), do: []

  defp objects_near(%{ra_deg: ra0, dec_deg: dec0}, fov, now) do
    r = fov / 2 * 1.25

    (Catalog.stars(6.5) ++ Catalog.dsos() ++ Ephemeris.objects(now, Pointing.site()))
    |> Enum.filter(&(Astro.separation_radec(&1.ra_deg, &1.dec_deg, ra0, dec0) < r))
    |> Enum.map(fn o ->
      {x, y} = gnomonic(o.ra_deg, o.dec_deg, ra0, dec0, fov)
      Map.merge(o, %{x: x, y: y, r: dot_r(o)})
    end)
    |> Enum.filter(&(&1.x * &1.x + &1.y * &1.y < @r * @r))
    |> Enum.sort_by(& &1.mag)
    |> Enum.take(400)
  end

  # Gnomonic (tangent plane) about the field centre, scaled so the field's
  # radius is @r. East is to the left, as through a star diagonal; north is up.
  defp gnomonic(ra, dec, ra0, dec0, fov) do
    d = :math.pi() / 180
    dra = (ra - ra0) * d
    {dec, dec0} = {dec * d, dec0 * d}
    cosc = :math.sin(dec0) * :math.sin(dec) + :math.cos(dec0) * :math.cos(dec) * :math.cos(dra)
    cosc = if abs(cosc) < 1.0e-9, do: 1.0e-9, else: cosc
    x = :math.cos(dec) * :math.sin(dra) / cosc
    y = (:math.cos(dec0) * :math.sin(dec) - :math.sin(dec0) * :math.cos(dec) * :math.cos(dra)) / cosc
    k = @r / (fov / 2 * d)
    {Float.round(-x * k, 1), Float.round(-y * k, 1)}
  end

  defp dot_r(%{mag: m}) when is_number(m), do: Float.round(max(0.8, 3.6 - 0.34 * m), 1)
  defp dot_r(_), do: 1.2

  defp off_field(%{ra_deg: ra0, dec_deg: dec0}, %{ra_deg: ra, dec_deg: dec, name: name}, fov) do
    sep = Astro.separation_radec(ra, dec, ra0, dec0)

    if sep > fov / 2 do
      {x, y} = gnomonic(ra, dec, ra0, dec0, fov)
      n = :math.sqrt(x * x + y * y)
      %{name: name, arcmin: round(sep * 60), x: Float.round(x / n * (@r - 12), 1), y: Float.round(y / n * (@r - 12), 1)}
    end
  end

  defp off_field(_, _, _), do: nil

  defp next_star(id, ctx) do
    case Lineup.next(id, ctx) do
      %{} = star -> star
      _ -> nil
    end
  rescue
    _ -> nil
  end

  # -- driving ---------------------------------------------------------------------------

  @impl true
  def handle_event("fov", %{"deg" => deg}, socket) do
    fov = case Float.parse(deg) do
      {v, _} when v in @fovs -> v
      _ -> socket.assigns.fov
    end

    Settings.put("eyepiece_fov_deg", fov)
    {:noreply, socket |> assign(fov: fov) |> compute()}
  end

  def handle_event("step", %{"deg" => deg}, socket) do
    step = case Float.parse(deg) do
      {v, _} -> v
      _ -> socket.assigns.step
    end

    {:noreply, assign(socket, step: step)}
  end

  def handle_event("nudge", %{"dir" => dir}, socket) do
    # Screen directions, x right and y up, as the field is drawn.
    vec = %{"up" => {0.0, 1.0}, "down" => {0.0, -1.0}, "left" => {-1.0, 0.0}, "right" => {1.0, 0.0}}[dir]
    ref = socket.assigns.refs[socket.assigns.selected]

    case screen_axis(socket, vec) do
      {axis, sign} when ref != nil ->
        safe(fn -> Mount.goto_relative(ref, axis, sign * socket.assigns.step) end)
        {:noreply, socket}

      _ ->
        {:noreply, notice(socket, Controller.Words.error(:not_homed))}
    end
  end

  def handle_event("centred", _, socket) do
    star = socket.assigns.next_star
    snap = socket.assigns.snap

    cond do
      is_nil(star) or is_nil(snap) -> {:noreply, notice(socket, "No star suggested")}
      not snap.homed -> {:noreply, notice(socket, Controller.Words.error(:not_homed))}
      true ->
        st = Lineup.add(snap, star)
        {:noreply, socket |> compute() |> notice("#{star.name} · #{st.n} star#{if st.n == 1, do: "", else: "s"}")}
    end
  end

  def handle_event("slew", _, socket) do
    star = socket.assigns.next_star
    ref = socket.assigns.refs[socket.assigns.selected]

    text =
      case star && Pointing.slew(ref, socket.assigns.snap, star, socket.assigns.ctx, track: true) do
        {:ok, _, _} -> "Going to #{star.name}"
        {:error, e} -> Pointing.refusal_words(e, star.name)
        nil -> "No star suggested"
      end

    {:noreply, notice(socket, text)}
  end

  def handle_event("stop", _, socket) do
    if id = socket.assigns.selected, do: Tracker.stop(id)
    if ref = socket.assigns.refs[socket.assigns.selected], do: safe(fn -> Mount.stop(ref) end)
    {:noreply, notice(socket, "Stopped")}
  end

  # Which axis, and which way, moves the picture the way the arrow points.
  #
  # A crooked mount does not move north when its Dec axis turns: the tube
  # swings about an axis that is tilted, so the field slides at an angle. So
  # rather than ask the sky compass, ask the field itself: turn each axis a
  # little on paper, see which way the stars would slide, and take the axis
  # that comes closest to the arrow. The arrows then do what they say on any
  # mount, however badly it is standing.
  defp screen_axis(%{assigns: %{snap: snap, ctx: ctx, centre: centre, fov: fov}}, {wx, wy})
       when is_map(snap) and is_map(centre) do
    eps = 0.25

    [:ra, :dec]
    |> Enum.flat_map(fn axis ->
      case star_slide(snap, ctx, centre, axis, eps, fov) do
        {sx, sy} ->
          n = :math.sqrt(sx * sx + sy * sy)
          if n < 1.0e-6, do: [], else: [{axis, 1, (sx * wx + sy * wy) / n}, {axis, -1, -(sx * wx + sy * wy) / n}]

        _ ->
          []
      end
    end)
    |> case do
      [] -> nil
      list -> list |> Enum.max_by(&elem(&1, 2)) |> then(fn {axis, sign, _} -> {axis, sign} end)
    end
  end

  defp screen_axis(_, _), do: nil

  # Where a star sitting at the centre would slide to, in screen units with y
  # up, if `axis` turned by `eps` degrees.
  defp star_slide(snap, ctx, centre, axis, eps, fov) do
    moved = update_in(snap, [Access.key(:axes), Access.key(axis), Access.key(:degrees)], &(&1 + eps))

    case Truth.looking_at(moved, ctx) do
      %{ra_deg: ra, dec_deg: dec} ->
        # the centre moves that way, so the stars appear to move the other way
        {x, y} = gnomonic(ra, dec, centre.ra_deg, centre.dec_deg, fov)
        {-x, y}

      _ ->
        nil
    end
  end

  defp notice(socket, text), do: assign(socket, notice: {text, System.unique_integer([:positive])})

  # -- render ----------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="eyepiece" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Home" section={Controller.Words.section("Mount", @selected)} />
        <.title>Eyepiece</.title>
        <.actions>
          
          <.help href={~p"/docs/eyepiece"} label="the eyepiece" />
          <.stop /></.actions>
      </:header>

      <Controller.Components.Status.status :if={@snap && !@nested} snap={@snap} id={@selected} compact />

      <.card :if={@centre} class="wide">
        <svg viewBox="-110 -110 220 220" class="eyepiece" role="img" aria-label={field_words(@centre, @target, @objects)}>
          <circle r={@r_field} class="ep-field" />
          <line x1={-@r_field} y1="0" x2={@r_field} y2="0" class="ep-hair" />
          <line x1="0" y1={-@r_field} x2="0" y2={@r_field} class="ep-hair" />
          <text x="0" y={-@r_field - 3} class="ep-mark" text-anchor="middle">N</text>
          <text x={-@r_field - 3} y="4" class="ep-mark" text-anchor="end">E</text>
          <text x={@r_field + 3} y="4" class="ep-mark">W</text>

          <%= for o <- @objects do %>
            <circle
              :if={o.kind not in [:planet, :moon]}
              cx={o.x}
              cy={o.y}
              r={o.r}
              class={["ep-star", o.kind not in [:star] && "ep-dso"]}
            />
            <circle :if={o.kind in [:planet, :moon]} cx={o.x} cy={o.y} r={max(o.r, 2.5)} class="ep-planet" />
            <text :if={@fov >= 5.0 and o[:name] != nil and o.mag < 3.5} x={o.x + o.r + 2} y={o.y + 3} class="ep-name">{o.name}</text>
          <% end %>

          <%!-- the thing being held, ringed, and an arrow to it when it is outside --%>
          <% t = @target && Enum.find(@objects, &(&1[:id] == @target[:id])) %>
          <circle :if={t} cx={t.x} cy={t.y} r="9" class="ep-target" />
          <g :if={@target_off}>
            <line x1="0" y1="0" x2={@target_off.x} y2={@target_off.y} class="ep-arrow" />
            <text x={@target_off.x} y={@target_off.y - 5} class="ep-name" text-anchor="middle">
              {@target_off.name} {@target_off.arcmin}′
            </text>
          </g>
        </svg>

        <div class="state-line">
          <strong>{centre_words(@centre, @target)}</strong>
          <span class="dim">{source_words(@centre)} · stars to magnitude 6, so a real eyepiece shows more · east is to the left, as through a diagonal</span>
        </div>

        <.seg label="field of view">
          <:opt :for={f <- @fovs} on={abs(@fov - f) < 0.01} click="fov" value={%{deg: f}}>{fov_label(f)}</:opt>
        </.seg>
      </.card>

      <.card :if={!@centre} title="Nothing to Look At Yet">
        <.hint>
          {if @snap && !@snap.homed,
            do: "Set home first: until then the encoders do not say which way the tube is turned.",
            else: "No mount is answering."}
        </.hint>
        <.row :if={@selected}><.btn navigate={~p"/setup/#{@selected}"}>Setup ›</.btn></.row>
      </.card>

      <%!-- centring: the same arrows as Nudge, next to the field --%>
      <.card :if={@centre} title="Center It">
        <div class="dpad dpad-eyepiece">
          <span></span>
          <.btn class="arrow" phx-click="nudge" phx-value-dir="up" aria-label="nudge north"><span aria-hidden="true">▲</span><small>N</small></.btn>
          <span></span>
          <.btn class="arrow" phx-click="nudge" phx-value-dir="left" aria-label="nudge east"><span aria-hidden="true">◀</span><small>E</small></.btn>
          <span class="dpad-centre"><b>{step_label(@step)}</b><small>per tap</small></span>
          <.btn class="arrow" phx-click="nudge" phx-value-dir="right" aria-label="nudge west"><span aria-hidden="true">▶</span><small>W</small></.btn>
          <span></span>
          <.btn class="arrow" phx-click="nudge" phx-value-dir="down" aria-label="nudge south"><span aria-hidden="true">▼</span><small>S</small></.btn>
          <span></span>
        </div>

        <.seg label="how far per tap">
          <:opt :for={s <- @steps} on={abs(@step - s) < 1.0e-6} click="step" value={%{deg: s}}>{step_label(s)}</:opt>
        </.seg>

        <div :if={@next_star} class="item">
          <div class="item-text">
            <strong>Star {star_number(@selected)}: {@next_star.name}</strong>
            <span class="dim">{Lineup.where_words(@next_star.alt, @next_star.az)}</span>
          </div>
          <.btn phx-click="slew" aria-label={"Go To #{@next_star.name}"}>Go To</.btn>
          <.btn variant="primary" phx-click="centred" aria-label={"Centered: #{@next_star.name} is in the middle of the eyepiece"}>Centered</.btn>
        </div>
      </.card>

      <.notice :if={!@nested} notice={@notice} />
    </.page>
    """
  end

  defp fov_label(f), do: "#{trunc(f)}°"

  defp step_label(s) when s < 0.1, do: "#{round(s * 60)}′"
  defp step_label(s), do: "#{round(s * 60)}′"

  defp star_number(id), do: length(Lineup.samples(id)) + 1

  defp centre_words(%{ra_deg: ra, dec_deg: dec}, nil), do: "Pointing at RA #{fmt(ra)}°, Dec #{fmt(dec)}°"
  defp centre_words(_, %{name: name}), do: "Tracking #{name}"

  defp source_words(%{source: :truth}), do: "What the simulated tube really sees"
  defp source_words(_), do: "Where the software believes the tube points"

  defp field_words(%{ra_deg: ra, dec_deg: dec}, target, objects) do
    "The eyepiece field at RA #{fmt(ra)}°, Dec #{fmt(dec)}°, #{length(objects)} objects#{if target, do: ", #{target.name} ringed"}"
  end

  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp fmt(_), do: Controller.Words.none()

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end

end
