defmodule Controller.ScopeNow do
  @moduledoc """
  What each telescope is doing right now, in one small summary every page
  shows the same way (the bar at the top of the shell): still, tracking,
  moving by hand, or **slewing**, with what it is going to and where it
  points. A slew moves a telescope a long way by itself, so it must never be
  something a person has to work out from numbers changing.

      %{id, state: :offline | :still | :tracking | :moving | :slewing,
        words: "Slewing to M33 Triangulum", target: "M33 Triangulum" | nil,
        where: "RA 01h 33m 51s · Dec +30° 39′" | "RA axis +21°39′ · Dec axis −14°58′",
        slew: nil | %{pct: 62, ra: 3.1, dec: 0.0}}

  `slew` is how far a Go To has got: the share of the turn done, and the
  degrees each axis still has to go. It is worked out from the Go To the
  driver logged (`Telescope.Events`: which axis, by how much) and where the
  axis stood then, so only on the machine the mount is plugged into.

  `state` comes from the driver's own snapshot (an axis with a Go To pending
  is slewing; a running axis with nothing holding it is being moved by hand).
  The target's name comes from the tracker on the machine the mount is
  plugged into, so a Mac in the cluster names a box's target too.

  **One machine speaks for a telescope: the one its mount is plugged into.**
  The summaries are broadcast across the cluster, so a Mac's pages show a
  box's telescope from the box's own word; the Mac works out nothing about it
  (it has neither its alignment nor its hold), only keeps what it hears, and
  asks the box once for a telescope it has not heard about yet. On 13 October
  2026 both machines published for the box's mount and its pages said "Still"
  under a hold, from the Mac.

  It follows its own mounts' four-a-second snapshots and says something
  (`{:scope_now, id, summary}` on `"scope_now"`) only when the state or the
  words change, and for the position at most once a second: a page is not
  redrawn four times a second for a toolbar.
  """
  use GenServer

  alias Controller.Sky.{Pointing, Tracker}

  @topic "scope_now"
  @rescan_ms 5_000
  # the position, and what the tracker says, are looked at this often
  @look_ms 1_000
  # faster than this an axis is being driven, not tracking (sidereal is 0.0042°/s)
  @driven_deg_s 0.02

  def start_link(_), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  def subscribe, do: Telescope.subscribe(@topic)

  @doc "Every telescope's summary, by id."
  def all do
    GenServer.call(__MODULE__, :all, 2_000)
  catch
    :exit, _ -> %{}
  end

  @doc "One telescope's summary, or nil."
  def get(id), do: Map.get(all(), id)

  # -- the summary, from what is known ------------------------------------------------------

  @doc """
  The summary for a mount's snapshot. `tracker` is `Controller.Sky.Tracker.status/1`
  for it (nil when nothing is held), `aligning?` whether an alignment run is
  moving it, `where` its position in words.
  """
  def summary(snap, tracker \\ nil, aligning? \\ false, where \\ nil)

  def summary(%{connected: true, axes: axes} = snap, tracker, aligning?, where) do
    target = is_map(tracker) && tracker[:name]
    slewing? = Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end)
    driven? = Enum.any?(axes, fn {_, ax} -> ax[:running] == true and abs(ax[:deg_per_s] || 0.0) > @driven_deg_s end)
    held? = is_map(tracker) or Map.get(snap, :tracking, :off) != :off

    {state, words} =
      cond do
        slewing? and aligning? -> {:slewing, "Slewing to the next alignment picture"}
        slewing? and is_binary(target) -> {:slewing, "Slewing to #{target}"}
        slewing? -> {:slewing, "Slewing"}
        driven? and not is_map(tracker) -> {:moving, "Moving"}
        aligning? -> {:tracking, "Aligning with the camera"}
        is_binary(target) -> {:tracking, "Tracking #{target}"}
        held? -> {:tracking, "Tracking"}
        true -> {:still, "Still"}
      end

    %{id: snap.id, state: state, words: words, target: target || nil, where: where, slew: nil}
  end

  def summary(%{id: id}, _tracker, _aligning?, _where), do: %{id: id, state: :offline, words: "Not answering", target: nil, where: nil, slew: nil}
  def summary(_, _, _, _), do: nil

  # -- the process --------------------------------------------------------------------------

  @impl true
  def init(_) do
    Telescope.Events.subscribe()
    # what other machines say about their own telescopes
    subscribe()
    send(self(), :rescan)
    # gotos: each Go To in flight, by mount and axis: where the axis stood and how far it was sent
    {:ok, %{now: %{}, subscribed: MapSet.new(), looked: %{}, known: %{}, axes: %{}, gotos: %{}, mine: MapSet.new()}}
  end

  @impl true
  def handle_call(:all, _from, s), do: {:reply, s.now, s}

  @impl true
  def handle_info(:rescan, s) do
    Process.send_after(self(), :rescan, @rescan_ms)
    refs = safe(fn -> Mount.list() end) || []
    # which machine each telescope is on, for everything that asks it (`Controller.Machine`)
    Controller.Machine.note(refs)

    # this machine's own mounts are followed and spoken for; another machine's are only listened to
    mine = for(ref <- refs, ref.node == node(), into: MapSet.new(), do: ref.id)

    subscribed =
      Enum.reduce(refs, s.subscribed, fn ref, acc ->
        if ref.node != node() or MapSet.member?(acc, ref.id), do: acc, else: (safe(fn -> Mount.subscribe(ref) end); MapSet.put(acc, ref.id))
      end)

    # a telescope on another machine that has said nothing yet (a steady hold changes nothing): ask once
    heard = for ref <- refs, ref.node != node(), not Map.has_key?(s.now, ref.id), now = Controller.Machine.ask(ref.node, __MODULE__, :get, [ref.id]), is_map(now), into: %{}, do: {ref.id, now}
    s = %{s | now: Map.merge(s.now, heard), mine: mine}

    # a mount that has gone is no longer on any page's bar
    ids = MapSet.new(refs, & &1.id)
    gone = for {id, _} <- s.now, not MapSet.member?(ids, id), do: id
    for id <- gone, MapSet.member?(s.mine, id) or not Enum.any?(refs, &(&1.id == id)), do: Telescope.broadcast(@topic, {:scope_now, id, nil})
    {:noreply, %{s | subscribed: subscribed, now: Map.drop(s.now, gone), known: Map.drop(s.known, gone), looked: Map.drop(s.looked, gone)}}
  end

  # another machine's word about its own telescope: kept, never spoken over
  def handle_info({:scope_now, id, now}, s) do
    cond do
      MapSet.member?(s.mine, id) -> {:noreply, s}
      is_nil(now) -> {:noreply, %{s | now: Map.delete(s.now, id)}}
      true -> {:noreply, %{s | now: Map.put(s.now, id, now)}}
    end
  end

  def handle_info({:mount, %{id: id} = snap}, s) when is_map_key(snap, :node) and :erlang.map_get(:node, snap) != node(), do: (_ = id; {:noreply, s})

  def handle_info({:mount, %{id: id} = snap}, s) do
    now = System.monotonic_time(:millisecond)
    last = Map.get(s.looked, id)
    # what the tracker and the model say is asked once a second; the driver's own word (slewing,
    # running) is in every snapshot, so a slew shows the moment it starts
    {known, s} =
      if is_nil(last) or now - last >= @look_ms do
        known = look(snap)
        {known, %{s | known: Map.put(s.known, id, known), looked: Map.put(s.looked, id, now)}}
      else
        {Map.get(s.known, id, %{tracker: nil, aligning?: false, where: nil}), s}
      end

    new = summary(snap, known.tracker, known.aligning?, known.where)
    s = %{s | axes: Map.put(s.axes, id, axes_deg(snap))}
    # a Go To's record lasts as long as the slew: once the axes have settled it is history
    s = if new.state != :slewing and match?(%{state: :slewing}, s.now[id]), do: %{s | gotos: Map.delete(s.gotos, id)}, else: s
    new = if new.state == :slewing, do: %{new | slew: progress(s.gotos[id], s.axes[id])}, else: new

    if new != s.now[id] do
      Telescope.broadcast(@topic, {:scope_now, id, new})
      {:noreply, %{s | now: Map.put(s.now, id, new)}}
    else
      {:noreply, s}
    end
  end

  # the driver sent an axis somewhere: from where it stands, by this much
  def handle_info({:event, %{module: :mount, name: :goto, data: %{id: id, axis: axis, degrees: by}}}, s) when is_number(by) do
    from = get_in(s.axes, [id, axis])
    if is_number(from), do: {:noreply, %{s | gotos: Map.update(s.gotos, id, %{axis => %{from: from, by: by}}, &Map.put(&1, axis, %{from: from, by: by}))}}, else: {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp axes_deg(%{axes: axes}), do: Map.new(axes, fn {k, ax} -> {k, ax[:degrees]} end)
  defp axes_deg(_), do: %{}

  @doc false
  # how far the Go Tos in flight have got: the share done, and what each axis has left
  def progress(gotos, axes) when is_map(gotos) and map_size(gotos) > 0 and is_map(axes) do
    parts =
      for {axis, %{from: from, by: by}} <- gotos, is_number(axes[axis]) do
        done = min(abs(axes[axis] - from), abs(by))
        {axis, done, abs(by)}
      end

    total = parts |> Enum.map(&elem(&1, 2)) |> Enum.sum()
    done = parts |> Enum.map(&elem(&1, 1)) |> Enum.sum()

    if total > 0 do
      left = Map.new(parts, fn {axis, d, of} -> {axis, Float.round(of - d, 1)} end)
      Map.merge(%{pct: round(100 * done / total), ra: 0.0, dec: 0.0}, left)
    end
  end

  def progress(_, _), do: nil

  # what only the mount's own machine knows (its tracker, its alignment run), and where it points
  defp look(%{id: id} = snap) do
    node = Map.get(snap, :node, node())

    %{
      tracker: on(node, Tracker, :status, [id]),
      aligning?: match?(%{done: false}, on(node, Controller.AutoAlign, :status, [id])),
      where: where(snap)
    }
  end

  defp on(node, m, f, a) when node == node(), do: safe(fn -> apply(m, f, a) end)

  defp on(node, m, f, a) do
    :erpc.call(node, m, f, a, 800)
  catch
    _, _ -> nil
  end

  @doc "Where a mount points, in words: on the sky when its alignment says, else its axes."
  def where(%{connected: true, id: id, axes: %{ra: ra, dec: dec}} = snap) do
    case safe(fn -> Pointing.scope_radec(snap, Pointing.context(DateTime.utc_now(), id)) end) do
      {r, d} when is_number(r) and is_number(d) -> "RA #{hms(r)} · Dec #{dms(d)}"
      _ -> "RA axis #{deg(ra.degrees)} · Dec axis #{deg(dec.degrees)}"
    end
  end

  def where(_), do: nil

  defp hms(ra) do
    s = round(ra / 15 * 3600)
    "#{pad(div(s, 3600))}h #{pad(rem(div(s, 60), 60))}m"
  end

  defp dms(dec) do
    m = round(abs(dec) * 60)
    "#{if dec < 0, do: "−", else: "+"}#{pad(div(m, 60))}° #{pad(rem(m, 60))}′"
  end

  defp deg(x) do
    m = round(abs(x) * 60)
    "#{if x < 0, do: "−", else: "+"}#{div(m, 60)}°#{pad(rem(m, 60))}′"
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end
end
