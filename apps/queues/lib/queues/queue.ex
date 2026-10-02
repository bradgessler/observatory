defmodule Queues.Queue do
  @moduledoc """
  One step of a pipeline: items wait their turn here and are worked on, up to
  `concurrency` at once, each in its own task (under `Queues.Tasks`, never
  linked), so a crash or a hang is that item's failure and nothing else's.

  Nothing waits on it. `Queues.push/3` answers at once: `:ok`, or
  `{:error, :full}` when the queue is at its limit (items or bytes), and
  the producer decides what that means (a preview frame is dropped, a
  science frame waits). With `overflow: :drop_oldest` the oldest waiting
  item makes room instead, and is counted as dropped.

  Options:

    * `name:` (required) and `label:`, the words a page shows; `step:` its
      place in its pipeline, for the order a page lists them in
    * `run:` (required) the work for one item: `fun(item)` or `{m, f, args}`
      (called as `apply(m, f, [item | args])`), returning `{:ok, _}`,
      `:ok` or `{:error, reason}`; or `{:ok, _, parts}` with `parts` a map of
      milliseconds by name (`%{"download" => 180, "ack" => 40}`), so the
      numbers say where inside the step its time goes
    * `concurrency:` (1), `max_items:` (100), `max_bytes:` (:infinity)
    * `overflow:` `:reject` (default) or `:drop_oldest`
    * `retries:` (0) more tries for an item whose work failed, after `backoff_ms:` (1000)
    * `timeout:` (60 s) the longest one item may take; then it's killed and failed
    * `bytes:` `fun(item)` the size an item counts as, when `push/3` isn't told

  Every finished item is timed (how long it waited, how long the work took,
  its bytes) and the last minute of those becomes the queue's numbers
  (`Queues.Meter`), sent on the `"queues"` topic every second and as
  `:telemetry` events `[:queues, :item, :done | :failed | :dropped]`.
  """
  use GenServer
  require Logger

  alias Queues.Meter

  @report_ms 1_000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: Queues.via(Keyword.fetch!(opts, :name)))
  end

  def child_spec(opts) do
    %{id: {__MODULE__, Keyword.fetch!(opts, :name)}, start: {__MODULE__, :start_link, [opts]}}
  end

  # -- the process --------------------------------------------------------------------------

  @impl true
  def init(opts) do
    Process.flag(:trap_exit, true)
    Process.send_after(self(), :report, @report_ms)

    {:ok,
     %{
       name: Keyword.fetch!(opts, :name),
       label: Keyword.get(opts, :label, to_string(opts[:name])),
       step: Keyword.get(opts, :step, 0),
       run: Keyword.fetch!(opts, :run),
       concurrency: Keyword.get(opts, :concurrency, 1),
       max_items: Keyword.get(opts, :max_items, 100),
       max_bytes: Keyword.get(opts, :max_bytes, :infinity),
       overflow: Keyword.get(opts, :overflow, :reject),
       retries: Keyword.get(opts, :retries, 0),
       backoff_ms: Keyword.get(opts, :backoff_ms, 1_000),
       timeout: Keyword.get(opts, :timeout, 60_000),
       bytes: Keyword.get(opts, :bytes, fn _ -> 0 end),
       q: :queue.new(),
       depth: 0,
       depth_bytes: 0,
       running: %{},
       counts: %{pushed: 0, done: 0, failed: 0, dropped: 0, rejected: 0},
       bytes_done: 0,
       meter: Meter.new(),
       last_error: nil,
       paused: false,
       parts: []
     }}
  end

  @impl true
  def handle_call({:push, item, opts}, _from, s) do
    bytes = Keyword.get_lazy(opts, :bytes, fn -> s.bytes.(item) end)
    entry = %{item: item, bytes: bytes, queued_at: Meter.now(), attempt: 0}

    cond do
      fits?(s, bytes) ->
        {:reply, :ok, s |> enqueue(entry) |> bump(:pushed) |> dispatch()}

      s.overflow == :drop_oldest and s.depth > 0 ->
        {:reply, :ok, s |> make_room(bytes) |> enqueue(entry) |> bump(:pushed) |> dispatch()}

      true ->
        event(s, :rejected, %{bytes: bytes})
        {:reply, {:error, :full}, bump(s, :rejected)}
    end
  end

  def handle_call(:stats, _from, s), do: {:reply, stats(s), s}
  def handle_call({:pause, on?}, _from, s), do: {:reply, :ok, dispatch(%{s | paused: on?})}
  def handle_call(:room, _from, s), do: {:reply, room(s), s}

  @impl true
  def handle_info({ref, result}, %{running: running} = s) when is_map_key(running, ref) do
    Process.demonitor(ref, [:flush])
    {:noreply, s |> finish(ref, result) |> dispatch()}
  end

  def handle_info({:DOWN, ref, :process, _, reason}, %{running: running} = s) when is_map_key(running, ref) do
    {:noreply, s |> finish(ref, {:error, {:crashed, reason}}) |> dispatch()}
  end

  def handle_info({:deadline, ref}, %{running: running} = s) when is_map_key(running, ref) do
    %{pid: pid} = running[ref]
    Process.demonitor(ref, [:flush])
    Process.exit(pid, :kill)
    {:noreply, s |> finish(ref, {:error, :timeout}) |> dispatch()}
  end

  def handle_info({:deadline, _}, s), do: {:noreply, s}
  def handle_info({:retry, entry}, s), do: {:noreply, s |> enqueue(entry, :front) |> dispatch()}

  def handle_info(:report, s) do
    Process.send_after(self(), :report, @report_ms)
    Telescope.broadcast("queues", {:queue, node(), s.name, stats(s)})
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  # work under way goes down with its queue: nothing is left running that nobody is waiting for
  @impl true
  def terminate(_reason, s) do
    for {_, %{pid: pid}} <- s.running, do: Process.exit(pid, :kill)
    :ok
  end

  # -- waiting ------------------------------------------------------------------------------

  defp fits?(s, bytes) do
    s.depth < s.max_items and (s.max_bytes == :infinity or s.depth_bytes + bytes <= s.max_bytes)
  end

  defp room(s) do
    items = max(s.max_items - s.depth, 0)
    if s.paused, do: 0, else: items
  end

  defp enqueue(s, entry, where \\ :back) do
    q = if where == :front, do: :queue.in_r(entry, s.q), else: :queue.in(entry, s.q)
    %{s | q: q, depth: s.depth + 1, depth_bytes: s.depth_bytes + entry.bytes}
  end

  defp make_room(s, bytes) do
    if fits?(s, bytes) or s.depth == 0 do
      s
    else
      {{:value, old}, q} = :queue.out(s.q)
      event(s, :dropped, %{bytes: old.bytes})
      %{s | q: q, depth: s.depth - 1, depth_bytes: s.depth_bytes - old.bytes} |> bump(:dropped) |> make_room(bytes)
    end
  end

  # -- working ------------------------------------------------------------------------------

  defp dispatch(%{paused: true} = s), do: s

  defp dispatch(s) do
    if map_size(s.running) < s.concurrency and s.depth > 0 do
      {{:value, entry}, q} = :queue.out(s.q)
      s = %{s | q: q, depth: s.depth - 1, depth_bytes: s.depth_bytes - entry.bytes}
      run = s.run
      task = Task.Supervisor.async_nolink(Queues.Tasks, fn -> work(run, entry.item) end)
      Process.send_after(self(), {:deadline, task.ref}, s.timeout)
      started = Meter.now()
      dispatch(%{s | running: Map.put(s.running, task.ref, %{entry: entry, pid: task.pid, started: started})})
    else
      s
    end
  end

  defp work(fun, item) when is_function(fun, 1), do: fun.(item)
  defp work({m, f, args}, item), do: apply(m, f, [item | args])

  defp finish(s, ref, result) do
    {%{entry: entry, started: started}, running} = Map.pop(s.running, ref)
    s = %{s | running: running}
    done = Meter.now()
    wait = started - entry.queued_at
    meas = %{wait_ms: wait, work_ms: done - started, bytes: entry.bytes}

    # a failure is time the worker spent too, so it counts toward how busy the step is
    s = %{s | meter: Meter.add(s.meter, started, done, wait, if(ok?(result), do: entry.bytes, else: 0))}

    cond do
      ok?(result) ->
        event(s, :done, meas)
        s = %{s | bytes_done: s.bytes_done + entry.bytes}
        s = with {:ok, _, %{} = p} <- result, do: %{s | parts: Enum.take([p | s.parts], 60)}, else: (_ -> s)
        bump(s, :done)

      entry.attempt < s.retries ->
        Process.send_after(self(), {:retry, %{entry | attempt: entry.attempt + 1}}, s.backoff_ms)
        %{s | last_error: words(reason(result))}

      true ->
        Logger.warning("queue #{s.name}: #{inspect(reason(result)) |> String.slice(0, 300)}")
        event(s, :failed, Map.put(meas, :reason, reason(result)))
        %{s | last_error: words(reason(result))} |> bump(:failed)
    end
  end

  defp ok?(:ok), do: true
  defp ok?(t) when is_tuple(t) and tuple_size(t) > 0 and elem(t, 0) == :ok, do: true
  defp ok?(_), do: false

  defp reason({:error, reason}), do: reason
  defp reason(other), do: {:unexpected, other}

  defp words(reason) when is_binary(reason), do: reason
  defp words(reason), do: inspect(reason) |> String.slice(0, 200)

  # -- numbers ------------------------------------------------------------------------------

  defp bump(s, key), do: %{s | counts: Map.update!(s.counts, key, &(&1 + 1))}

  defp event(s, what, meas), do: :telemetry.execute([:queues, :item, what], meas, %{queue: s.name, node: node()})

  defp stats(s) do
    now = Meter.now()
    starts = s.running |> Map.values() |> Enum.map(& &1.started)

    oldest =
      case :queue.peek(s.q) do
        {:value, e} -> now - e.queued_at
        :empty -> 0
      end

    Map.merge(Meter.read(s.meter, starts, s.concurrency, now), %{
      name: s.name,
      label: s.label,
      step: s.step,
      kind: :queue,
      depth: s.depth,
      depth_bytes: s.depth_bytes,
      max_items: s.max_items,
      running: map_size(s.running),
      concurrency: s.concurrency,
      oldest_wait_ms: oldest,
      counts: s.counts,
      paused: s.paused,
      # running totals: a page turns the change from one second to the next into rates
      total: s.counts.done,
      total_bytes: s.bytes_done,
      last_error: s.last_error,
      parts: parts(s.parts)
    })
  end

  # the middle of the last 60 items' parts, by name
  defp parts([]), do: nil

  defp parts(list) do
    list
    |> Enum.flat_map(&Map.to_list/1)
    |> Enum.group_by(&elem(&1, 0), &elem(&1, 1))
    |> Map.new(fn {k, v} -> {k, v |> Enum.sort() |> Enum.at(div(length(v), 2))} end)
  end
end
