defmodule Queues.Board do
  @moduledoc """
  The last numbers from every queue and spool on the cluster, by node and
  name, kept as they arrive on `"queues"`, and the last 5 minutes of each
  as a history a page can draw: a point a second with items and bytes a
  second (from the change in the running totals), how many waited, how
  busy it was, and the middle wait and work. A queue not heard from for
  5 s (its node left, or it stopped) drops off.
  """
  use GenServer

  @stale_ms 5_000
  # 5 minutes at a point a second
  @keep 300

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Every queue heard from lately: this node first, then by node, step and name."
  def list do
    GenServer.call(__MODULE__, :list)
  catch
    :exit, _ -> []
  end

  @impl true
  def init(_) do
    Telescope.subscribe("queues")
    {:ok, %{}}
  end

  @impl true
  def handle_call(:list, _from, seen) do
    now = System.monotonic_time(:millisecond)
    seen = Map.reject(seen, fn {_, {at, _, _}} -> now - at > @stale_ms end)

    list =
      seen
      |> Enum.sort_by(fn {{node, name}, {_, s, _}} -> {node != node(), to_string(node), Map.get(s, :step, 0), to_string(name)} end)
      |> Enum.map(fn {_, {_, s, history}} -> Map.put(s, :history, Enum.reverse(history)) end)

    {:reply, list, seen}
  end

  @impl true
  def handle_info({:queue, node, name, stats}, seen) do
    now = System.monotonic_time(:millisecond)
    stats = Map.put(stats, :node, node)

    history =
      case seen[{node, name}] do
        {at, prev, history} -> Enum.take([point(stats, prev, now - at) | history], @keep)
        nil -> []
      end

    {:noreply, Map.put(seen, {node, name}, {now, stats, history})}
  end

  def handle_info(_, seen), do: {:noreply, seen}

  # one second of a step: from the change in its running totals when it has them, else its own rate
  defp point(s, prev, dt_ms) do
    dt = max(dt_ms, 1) / 1000

    %{
      per_s: rate(s[:total], prev[:total], dt) || s[:per_s] || 0.0,
      bytes_per_s: rate(s[:total_bytes], prev[:total_bytes], dt) || (s[:mb_per_s] || 0.0) * 1_048_576,
      depth: s[:depth] || 0,
      busy: s[:busy] || 0.0,
      wait_ms: get_in(s, [:wait_ms, :p50]),
      work_ms: get_in(s, [:work_ms, :p50])
    }
  end

  defp rate(now, before, dt) when is_number(now) and is_number(before) and now >= before, do: (now - before) / dt
  defp rate(_, _, _), do: nil
end
