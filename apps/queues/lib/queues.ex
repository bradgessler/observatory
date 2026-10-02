defmodule Queues do
  @moduledoc """
  Pipelines of work that never block, and say where they're slow.

  A frame from the telescope camera goes through several steps: written to
  the box's SD card, copied to the Mac, measured, solved. Each step is a
  queue (`Queues.Queue`): items wait their turn, a few are worked on at once,
  each in its own task, and a producer is told at once when there's no room
  rather than made to wait. Files that have to outlive a restart wait on
  disk instead (`Queues.Spool`), within a byte budget and a floor of free
  space.

  Every queue and spool times its work: how long items wait, how long they
  take, how many a second, how busy the workers are. The numbers go out on
  the cluster's PubSub every second, so `Queues.board/0` on any machine has
  every machine's, and `Queues.bottleneck/1` names the slow step: the one
  that's busy all the time with work piling up in front of it.

      Queues.push("frames.write", frame, bytes: byte_size(frame.pgm))
      Queues.board()            # [%{node, name, label, depth, wait_ms, work_ms, busy, ...}]
      Queues.bottleneck(Queues.board())
  """

  @doc "Where a queue or spool named `name` is registered on this node."
  def via(name), do: {:via, Registry, {Queues.Registry, name}}

  @doc """
  Offer `item` to queue `name`: `:ok`, or `{:error, :full}` at once when
  there's no room (`{:error, :no_queue}` when there's no such queue). Never
  waits for the work. `bytes:` what the item counts as against `max_bytes:`.
  """
  def push(name, item, opts \\ []) do
    GenServer.call(via(name), {:push, item, opts}, 5_000)
  catch
    :exit, {:noproc, _} -> {:error, :no_queue}
    :exit, {:timeout, _} -> {:error, :busy}
    :exit, _ -> {:error, :no_queue}
  end

  @doc "How many more items queue `name` would take now (0 when it's paused or full)."
  def room(name) do
    GenServer.call(via(name), :room, 5_000)
  catch
    :exit, _ -> 0
  end

  @doc "Stop (true) or restart (false) handing out work; waiting items stay."
  def pause(name, on?), do: GenServer.call(via(name), {:pause, on?})

  @doc "This node's numbers for one queue or spool."
  def stats(name), do: GenServer.call(via(name), :stats)

  @doc "Every queue and spool on this node, by name."
  def local do
    for name <- Registry.select(Queues.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}]),
        s = safe_stats(name),
        s != nil,
        do: Map.put(s, :node, node())
  end

  defp safe_stats(name) do
    stats(name)
  catch
    :exit, _ -> nil
  end

  @doc "Every queue and spool heard from on the cluster in the last few seconds."
  defdelegate board, to: Queues.Board, as: :list

  @doc "Numbers as they change: `{:queue, node, name, stats}` every second per queue."
  def subscribe, do: Telescope.subscribe("queues")

  @doc """
  The step holding the rest up, or nil when nothing is: the busiest queue
  that's at least 80% busy, or failing to keep its waiting line from growing
  (something has waited 10 s or more). Ties go to the longer wait.
  """
  def bottleneck(stats) do
    stats
    |> Enum.filter(&(&1.busy >= 0.8 or &1.oldest_wait_ms >= 10_000))
    |> Enum.max_by(&{&1.busy, &1.oldest_wait_ms}, fn -> nil end)
  end
end
