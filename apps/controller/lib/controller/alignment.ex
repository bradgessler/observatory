defmodule Controller.Alignment do
  @moduledoc """
  How well each telescope is aligned, in one summary: whether home is set,
  how many alignment points there are, how closely they agree (the margin a
  Go To lands within), and what that is good for. Every page shows it the
  same way (`Controller.Components.AlignmentStatus`): in the sidebar for the
  telescope you're driving, beside each one in the switcher, and in the
  toolbar of the Alignment pages.

  The points and their fit live in `Controller.Sky.Lineup` (centred stars,
  or an Align by Photo fit handed to it); home lives in the mount. This only
  reads them.

      Alignment.summary("sim-eq")
      #=> %{state: :aligned, n: 4, margin_arcmin: 3.2, tier: :planets, words: "±3′ · 4 points", ...}

  `Controller.Alignment.Watch` keeps each one current and broadcasts
  `{:alignment, id, summary}` on `"alignment"` when one changes, so a page
  never polls for it.
  """

  alias Controller.Sky.Lineup

  @topic "alignment"

  # the margins the goals are judged by (Lineup's), loosest first: how many of the bullseye's rings light
  @tiers [{:look, 30.0, "just look"}, {:planets, 10.0, "Moon and planets"}, {:deep, 2.0, "deep sky"}]

  def topic, do: @topic
  def subscribe, do: Telescope.subscribe(@topic)

  @doc """
  The latest summary for a telescope, from the machine it's plugged into
  (a box keeps its own alignment points): this machine's watcher, or the box's.
  """
  def get(nil), do: none(nil)

  def get(id) do
    case ref(id) do
      %{node: n} when n != node() -> remote(n, id)
      _ -> local(id)
    end
  end

  defp remote(n, id) do
    :erpc.call(n, __MODULE__, :get, [id], 3_000)
  catch
    _, _ -> none(id)
  end

  # the watcher's, or (it gave up, or is restarting) worked out here; never a crash for the page
  defp local(id) do
    Controller.Alignment.Watch.get(id)
  catch
    :exit, _ ->
      try do
        summary(id)
      rescue
        _ -> none(id)
      end
  end

  @doc false
  def ref(id) do
    Enum.find(Mount.list(), &(&1.id == id))
  catch
    _, _ -> nil
  end

  @doc """
  One telescope's alignment, worked out now:

    * `state`: `:none` (no home, no points), `:home` (home set, no points: Go
      To assumes a perfectly polar-aligned mount), `:points` (one or two:
      they fit exactly, so the margin can't be measured yet), `:aligned`
      (three or more: the margin is measured);
    * `n`, `homed`, `margin_arcmin` (the rms of the fit, three or more points);
    * `tier`: the tightest goal the margin meets (`:look`, `:planets`,
      `:deep`) or nil; `rings`: how many of the bullseye's three rings light;
    * `words`: one short line ("±3′ · 4 points"); `detail`: what it's good for.
  """
  def summary(nil), do: none(nil)

  def summary(id) do
    status = safe(fn -> Lineup.status(id) end, %{n: 0, rms_arcmin: nil, good_for: []})
    homed = safe(fn -> Mount.snapshot(ref(id) || id).homed end, false)
    n = status.n
    # a margin is measured from three or more points that agree on a number (a photo fit may not give one)
    margin = if n >= 3 and is_number(status.rms_arcmin), do: status.rms_arcmin

    {tier, rings} =
      case margin && Enum.filter(@tiers, fn {_, lim, _} -> margin <= lim end) do
        nil -> {nil, 0}
        [] -> {nil, 0}
        met -> {met |> List.last() |> elem(0), length(met)}
      end

    state =
      cond do
        margin != nil -> :aligned
        n > 0 -> :points
        homed -> :home
        true -> :none
      end

    %{
      id: id,
      state: state,
      n: n,
      homed: homed,
      margin_arcmin: margin,
      tier: tier,
      rings: rings,
      words: words(state, n, margin),
      detail: detail(state, tier, margin)
    }
  end

  defp none(id), do: %{id: id, state: :none, n: 0, homed: false, margin_arcmin: nil, tier: nil, rings: 0, words: "Not aligned", detail: "No home set and no alignment points"}

  defp words(:none, _, _), do: "Not aligned"
  defp words(:home, _, _), do: "Home set · no points"
  defp words(:points, n, _), do: "#{n} #{points(n)} · margin unknown"
  defp words(:aligned, n, m), do: "±#{arcmin(m)} · #{n} #{points(n)}"

  defp detail(:none, _, _), do: "Set home, or add a point by stars or by photo"
  defp detail(:home, _, _), do: "Go To assumes the mount is polar aligned. Add points to measure it"
  defp detail(:points, _, _), do: "One or two points fit exactly; a third measures the margin"
  defp detail(:aligned, nil, _), do: "Too loose to land things: forget the worst point, or add more"

  defp detail(:aligned, tier, _) do
    {_, _, goal} = Enum.find(@tiers, &(elem(&1, 0) == tier))
    "Good for #{goal}"
  end

  defp points(1), do: "point"
  defp points(_), do: "points"

  defp arcmin(m) when m < 10, do: "#{:erlang.float_to_binary(m * 1.0, decimals: 1)}′"
  defp arcmin(m), do: "#{round(m)}′"

  @doc "The tiers, loosest first: `[{key, margin_arcmin, goal}]`."
  def tiers, do: @tiers

  defp safe(fun, default) do
    fun.()
  rescue
    _ -> default
  catch
    _, _ -> default
  end
end

defmodule Controller.Alignment.Watch do
  @moduledoc """
  Keeps every telescope's alignment summary current and says when one
  changes (`{:alignment, id, summary}` on `"alignment"`): when an alignment
  point is added or forgotten (the "lineup" setting), when the location
  changes, when a mount is homed, comes or goes. Not on every mount report:
  four a second is for position, and alignment only moves with those events.
  """
  use GenServer

  alias Controller.Alignment

  @rescan_ms 5_000

  def start_link(_), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  @doc "The summary for `id`, as last worked out."
  def get(id), do: GenServer.call(__MODULE__, {:get, id}, 2_000)

  @impl true
  def init(_) do
    Controller.Settings.subscribe()
    send(self(), :rescan)
    {:ok, %{summaries: %{}, subscribed: MapSet.new(), seen: %{}}}
  end

  @impl true
  def handle_call({:get, id}, _from, state) do
    case state.summaries do
      %{^id => s} ->
        {:reply, s, state}

      # a mount this hasn't met (just plugged in): watch it from now, not from the next rescan
      _ ->
        state = watch(state, id)
        s = case safe_summary(id) do
          {:ok, s} -> s
          :error -> Alignment.summary(nil)
        end

        {:reply, s, put_in(state.summaries[id], s)}
    end
  end

  defp watch(state, id) do
    if MapSet.member?(state.subscribed, id) do
      state
    else
      Mount.subscribe(id)
      %{state | subscribed: MapSet.put(state.subscribed, id)}
    end
  end

  @impl true
  def handle_info(:rescan, state) do
    Process.send_after(self(), :rescan, @rescan_ms)
    ids = safe_ids()

    subscribed =
      Enum.reduce(ids, state.subscribed, fn id, acc ->
        if MapSet.member?(acc, id) do
          acc
        else
          Mount.subscribe(id)
          MapSet.put(acc, id)
        end
      end)

    {:noreply, refresh(%{state | subscribed: subscribed}, ids)}
  end

  def handle_info({:settings, key, _}, state) when key in ["lineup", "site", "pointing"],
    do: {:noreply, refresh(state, Map.keys(state.summaries))}

  def handle_info({:settings, _, _}, state), do: {:noreply, state}

  # a mount report: only home (and whether it answers) moves alignment
  def handle_info({:mount, %{id: id} = snap}, state) do
    key = {snap[:homed], snap[:homed_at], snap[:connected]}

    if state.seen[id] == key,
      do: {:noreply, state},
      else: {:noreply, %{state | seen: Map.put(state.seen, id, key)} |> refresh([id])}
  end

  def handle_info(_, state), do: {:noreply, state}

  # one telescope's summary failing keeps its last one; it never takes the others (or this) down
  defp refresh(state, ids) do
    summaries =
      Enum.reduce(ids, state.summaries, fn id, acc ->
        case safe_summary(id) do
          {:ok, s} ->
            if acc[id] != s, do: Telescope.broadcast(Alignment.topic(), {:alignment, id, s})
            Map.put(acc, id, s)

          :error ->
            acc
        end
      end)

    %{state | summaries: summaries}
  end

  defp safe_summary(id) do
    {:ok, Alignment.summary(id)}
  rescue
    e ->
      require Logger
      Logger.warning("alignment: #{id}: #{Exception.message(e)}")
      :error
  end

  # this machine's own mounts: a box's are watched (and broadcast) by the box
  defp safe_ids do
    Mount.list() |> Enum.filter(&(&1.node == node())) |> Enum.map(& &1.id)
  catch
    _, _ -> []
  end
end

defmodule Controller.Alignment.Supervisor do
  @moduledoc """
  The alignment watcher's own branch: restarted a few times if it crashes,
  then left down (its parent starts it `:temporary`), so a fault in working
  out alignment can never take the app with it. With the watcher down, pages
  work alignment out themselves (`Controller.Alignment.get/1`).
  """
  use Supervisor

  def start_link(_), do: Supervisor.start_link(__MODULE__, nil, name: __MODULE__)

  @impl true
  def init(_), do: Supervisor.init([Controller.Alignment.Watch], strategy: :one_for_one, max_restarts: 5, max_seconds: 60)
end
