defmodule Controller.LineupLive do
  @moduledoc """
  Star Align: set the mount down anyhow, name a few stars, and the software
  works out how it is really sitting. One star at a time: we suggest one and
  say where to look, you centre it with any control surface, you tap
  "that's it". After two the mount can be steered in the sky; after three we
  can say how well. No Polaris needed.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Pointing, Tracker}

  @impl true
  def mount(params, session, socket) do
    if connected?(socket) do
      send(self(), :rescan)
      Settings.subscribe()
      :timer.send_interval(5_000, :tick)
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
       picking: false,
       notice: nil
     )
     |> rescan()
     |> compute()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, socket |> rescan() |> compute()}
  end

  def handle_info(:tick, socket), do: {:noreply, compute(socket)}

  def handle_info({:mount, snap}, socket) do
    if snap.id == socket.assigns.selected, do: {:noreply, assign(socket, snap: snap)}, else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "lineup", _}, socket), do: {:noreply, compute(socket)}
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

  # Everything the page says, recomputed on a slow tick: the status, the
  # suggested next star, the candidate list, and "you're probably on…".
  defp compute(%{assigns: %{selected: nil}} = socket), do: assign(socket, status: nil, next: nil, candidates: [], guesses: [], samples: [], tracker: nil, site: Pointing.site(), now: DateTime.utc_now())

  defp compute(socket) do
    id = socket.assigns.selected
    ctx = Pointing.context(DateTime.utc_now(), id)
    candidates = Lineup.candidates(id, ctx, 6)

    assign(socket,
      site: Pointing.site(),
      now: DateTime.utc_now(),
      status: Lineup.status(id),
      next: List.first(candidates),
      candidates: candidates,
      guesses: if(socket.assigns.snap, do: Lineup.guess(socket.assigns.snap, ctx, 3), else: []),
      # stars taken before the axes were re-zeroed count from a zero that is gone: not shown
      samples: if(Lineup.stale?(id), do: [], else: Lineup.samples(id)),
      tracker: Tracker.status(id)
    )
  end

  # -- events -------------------------------------------------------------------------

  @impl true
  def handle_event("home", _, socket), do: {:noreply, socket |> run(&Mount.set_home/1) |> put_notice("zeroed")}

  # Rough slew toward the suggested star through whatever model we have so far
  def handle_event("slew", %{"id" => sid}, socket) do
    star = Controller.Sky.Stars.get(sid)
    ref = socket.assigns.refs[socket.assigns.selected]
    ctx = Pointing.context(DateTime.utc_now(), socket.assigns.selected)

    notice =
      case star && Pointing.slew(ref, socket.assigns.snap, star, ctx, track: true) do
        {:ok, _, _} -> "slewing to #{star.name}"
        {:error, :not_homed} -> "zero the axes first"
        {:error, :limit} -> "#{star.name} is outside the soft limits from here"
        {:error, e} -> inspect(e)
        nil -> "no such star"
      end

    {:noreply, socket |> assign(picking: false) |> put_notice(notice)}
  end

  # "That's it": the tube is on this star right now
  def handle_event("centred", %{"id" => sid}, socket) do
    star = Controller.Sky.Stars.get(sid)
    snap = socket.assigns.snap

    cond do
      is_nil(star) or is_nil(snap) -> {:noreply, put_notice(socket, "no mount")}
      not snap.homed -> {:noreply, put_notice(socket, "zero the axes first")}
      slewing?(snap) -> {:noreply, put_notice(socket, "still slewing")}
      true ->
        st = Lineup.add(snap, star)
        {:noreply, socket |> assign(picking: false) |> compute() |> put_notice(words_after(st, star))}
    end
  end

  def handle_event("drop", %{"i" => i}, socket) do
    Lineup.drop(socket.assigns.selected, String.to_integer(i))
    {:noreply, compute(socket)}
  end

  def handle_event("clear", _, socket) do
    Tracker.stop(socket.assigns.selected)
    Lineup.clear(socket.assigns.selected)
    {:noreply, socket |> compute() |> put_notice("alignment cleared")}
  end

  # Hold whatever the tube is on right now — centred by hand, no goto needed.
  # Through the line-up when there is one, the ideal geometry otherwise.
  def handle_event("hold", _, socket) do
    snap = socket.assigns.snap
    ctx = Pointing.context(DateTime.utc_now(), socket.assigns.selected)

    case snap && Pointing.scope_radec(snap, ctx) do
      {ra, dec} ->
        name = case Lineup.guess(snap, ctx, 1) do
          [%{away_deg: d, name: n}] when d < 1.0 -> n
          _ -> "here"
        end

        Tracker.track(socket.assigns.selected, %{name: name, ra_deg: ra, dec_deg: dec})
        {:noreply, socket |> compute() |> put_notice("holding #{name}")}

      _ ->
        {:noreply, put_notice(socket, "zero the axes first")}
    end
  end

  def handle_event("release", _, socket) do
    Tracker.stop(socket.assigns.selected)
    {:noreply, socket |> compute() |> put_notice("released")}
  end

  def handle_event("pick", _, socket), do: {:noreply, assign(socket, picking: !socket.assigns.picking)}
  def handle_event("dismiss", _, socket), do: {:noreply, assign(socket, notice: nil)}

  defp words_after(%{n: 1}, star), do: "#{star.name} · 1 star"
  defp words_after(%{n: 2}, star), do: "#{star.name} · 2 stars"
  defp words_after(st, star), do: "#{star.name} · #{st.n} stars · agree to #{fmt(st.rms_arcmin)}′"

  defp put_notice(socket, text), do: assign(socket, notice: text)

  defp run(socket, fun) do
    case socket.assigns.refs[socket.assigns.selected] do
      nil ->
        put_notice(socket, "no mount")

      ref ->
        try do
          case fun.(ref) do
            :ok -> socket
            {:error, e} -> put_notice(socket, inspect(e))
          end
        catch
          :exit, _ -> put_notice(socket, "mount unreachable")
        end
    end
  end

  # -- render -------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="lineup" night={@night} class={@nested && "nested"}>
      <:header :if={!@nested}>
        <.back navigate={~p"/"} label="Start" />
        <.title>{@selected} · Star Align</.title>
        <.actions><.help href={~p"/docs/align"} /></.actions>
      </:header>

      <%!-- where we stand, in one line --%>
      <.card :if={@status} class={"lineup-status#{if @status.solved?, do: " ok", else: ""}"}>
        <div class="state-line">
          <strong :if={!@status.solved?}>Not aligned</strong>
          <strong :if={@status.solved? and @status.n >= 3}>{@status.n} stars · agree to {fmt(@status.rms_arcmin)}′</strong>
          <strong :if={@status.solved? and @status.n < 3}>{@status.n} star{if @status.n == 1, do: "", else: "s"} · aligned, not yet checked</strong>
          <span :if={@status.solved?} class="dim">{@status.axis_words}</span>
          <span :if={@status.solved? and @status.good_for != []} class="dim">good for {Enum.join(@status.good_for, " · ")}</span>
          <span :if={@status.solved? and @status.n < 3} class="dim">{3 - @status.n} more to check it</span>
          <span :if={@status.solved? and @status.good_for == [] and @status.n >= 3 and @status.rms_arcmin < 120} class="dim">one star is off: forget the worst below</span>
          <span :if={@status.solved? and @status.n >= 2 and @status.rms_arcmin >= 120} class="dim">disagree by {fmt(@status.rms_arcmin / 60)}°. One isn't that star: forget the worst below</span>
          <span :if={@status.signs_corrected?} class="dim">axis sign corrected (Modes)</span>
        </div>
      </.card>

      <%!-- the two facts the maths needs, and where to change them; calm, never a nag --%>
      <.hint :if={@status} class="site-line">
        Site {@site.name} · {fmt2(@site.lat)}°, {fmt2(@site.lon)}° · clock {Calendar.strftime(@now, "%H:%M")} UTC ·
        <.link navigate={~p"/sky/#{@selected}?tab=horizon"}>change</.link>
        <span :if={@site.name == "nowhere"}> · <b>no site set</b></span>
      </.hint>

      <%!-- step 0: home, for the limits --%>
      <.card :if={@snap && !@snap.homed} title="First: Zero the Axes">
        <.hint>Counterweight down, tube along the polar axis. By eye is fine.</.hint>
        <.btn variant="primary" phx-click="home" data-confirm="Zero both axes at the current position?">Zero the axes here</.btn>
      </.card>

      <%!-- the next star --%>
      <.card :if={@snap && @snap.homed && @next && !@picking} title={"Star #{length(@samples) + 1}"}>
        <div class="star-next">
          <strong>{@next.name}</strong>
          <span>{@next.where} · magnitude {fmt(@next.mag)}</span>
        </div>
        <.row>
          <.btn phx-click="slew" phx-value-id={@next.id} disabled={slewing?(@snap)}>{if slewing?(@snap), do: "Slewing…", else: "Slew near it"}</.btn>
          <.btn variant="primary" phx-click="centred" phx-value-id={@next.id} disabled={slewing?(@snap)}>On it</.btn>
        </.row>
        <.row>
          <.btn class="btn-ghost" phx-click="pick">A different star ›</.btn>
          <.btn class="btn-ghost" navigate={~p"/controls/nudge/#{@selected}"}>Centre it ›</.btn>
        </.row>
        <.hint :if={@samples == []}>First slew is a guess. Watch the cable.</.hint>
      </.card>

      <.card :if={@snap && @snap.homed && @next && @picking} title="Which Star?">
        <.item :for={c <- @candidates} label={c.name} detail={c.where}>
          <.btn phx-click="slew" phx-value-id={c.id}>Slew</.btn>
          <.btn variant="primary" phx-click="centred" phx-value-id={c.id}>On it</.btn>
        </.item>
        <.row><.btn class="btn-ghost" phx-click="pick">Back</.btn></.row>
      </.card>

      <.card :if={@snap && @snap.homed && !@next} title="Nothing Bright Enough Is Up">
        <.hint>No named star above 20°. Try later, or Sync on the Sky page.</.hint>
      </.card>

      <%!-- what am I on? --%>
      <.card :if={@guesses != [] and @snap && @snap.homed} title="Probably Pointing At">
        <.item :for={g <- @guesses} label={g.name} detail={"#{fmt(g.away_deg)}° away · #{g.where}"}>
          <.btn phx-click="centred" phx-value-id={g.id}>On it</.btn>
        </.item>
      </.card>

      <%!-- the stars so far --%>
      <.card :if={@samples != []} title="Stars So Far">
        <.item :for={{s, i} <- Enum.with_index(@samples)} label={s["name"]} detail={"#{String.slice(s["at"], 11, 5)} UTC#{residual(@status, i)}"}>
          <.btn class="btn-ghost" phx-click="drop" phx-value-i={i} aria-label={"forget #{s["name"]}"}>✕</.btn>
        </.item>
        <.row>
          <.btn class="btn-ghost" phx-click="clear" data-confirm="Forget the whole line-up?">Start over</.btn>
        </.row>
      </.card>

      <%!-- tracking: hold whatever is in the eyepiece, or see how the hold is going --%>
      <.card :if={@snap && @snap.homed} title="Tracking">
        <div :if={@tracker} class="state-line">
          <strong>Holding {@tracker.name}{if @tracker.paused, do: " · paused while you drive", else: ""}</strong>
          <span class="dim">RA {fmt(@tracker.ra_rate)}× · Dec {fmt(@tracker.dec_rate)}× · {if @tracker.error_arcmin, do: "#{fmt(@tracker.error_arcmin)}′ off", else: "settling"}</span>
        </div>
        <.row>
          <.btn :if={!@tracker} variant="primary" phx-click="hold">Hold what I'm on</.btn>
          <.btn :if={@tracker} phx-click="release">Stop holding</.btn>
        </.row>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp residual(%{residuals_arcmin: res}, i) when is_list(res) do
    case Enum.at(res, i) do
      nil -> ""
      r when length(res) >= 3 -> " · off by #{fmt(r)}′"
      _ -> ""
    end
  end

  defp residual(_, _), do: ""

  defp slewing?(%{axes: axes}) when is_map(axes), do: Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end)
  defp slewing?(_), do: false

  defp fmt2(x), do: :erlang.float_to_binary(x / 1, decimals: 2)
  defp fmt(nil), do: "—"
  defp fmt(x), do: :erlang.float_to_binary(x / 1, decimals: 1)

  # keep the compiler honest about the alias we use in guesses/candidates words
  @doc false
  def _astro, do: Astro
end
