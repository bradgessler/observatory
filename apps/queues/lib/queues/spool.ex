defmodule Queues.Spool do
  @moduledoc """
  Files on disk waiting to be taken somewhere else: the box's frames waiting
  for the Mac. A queue whose items outlive a restart, a pulled plug and a
  Mac that's asleep, and that never fills the card.

  **Putting.** `put/4` writes the file in the caller's process (a queue's
  worker, never this one, so a slow card holds up nobody else): room is
  reserved first, the bytes go to `<id>.part` and are checksummed (SHA-256),
  then renamed into place and recorded in the spool's index (`index:`, a
  `Queues.Spool.Index`: by default a small `<id>.meta` beside each file; an
  application with a database passes its own). No room is an answer
  (`{:error, :full}`), not a wait.

  **Taking.** Another node leases a few files (`lease/3`), fetches them (the
  bytes go over HTTP, not the cluster: a 50 MB raw frame on the cluster's one
  connection would hold up every mount snapshot and STOP behind it), and
  acks each (`ack/2`), or releases it to be leased again. A lease nobody acks
  in `lease_ms` (60 s) runs out and the file is offered again. At most
  `max_leased` (2) are out at once: that's how many copies run in parallel.

  **Room.** Two limits, both checked before every write and every 10 s:
  `budget_bytes` (the most the spool may hold, by default a quarter of the
  free space it found at start, at most 4 GB) and `min_free_bytes` (1 GB,
  what the card keeps free for everything else). When either is crossed,
  files already taken are deleted oldest first; if that's not enough, `put`
  says `:full` until the Mac catches up. Taken files otherwise stay, newest
  kept, as a second copy.

  **How many.** `max_files:` (`:infinity`) keeps at most that many files:
  past it, the oldest go, files already taken first, then the oldest
  waiting ones. The newest always win, so a Mac that's been away comes back
  to the most recent frames, not a backlog. `paused:` (false) stops leases:
  files wait on the card (within the limits) until it's lifted. Either can
  be a function, asked each time, so a setting changes it without a restart.

  **Numbers.** Like a queue's (`Queues.Queue`): files waiting (and bytes),
  the oldest one's wait, put-to-lease wait and lease-to-ack time, files and
  MB a second taken, plus the card: bytes used, the budget, free space.
  """
  use GenServer
  require Logger

  alias Queues.Meter

  @report_ms 1_000
  @tidy_ms 10_000
  @max_budget 4 * 1024 * 1024 * 1024

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: Queues.via(Keyword.fetch!(opts, :name)))
  def child_spec(opts), do: %{id: {__MODULE__, Keyword.fetch!(opts, :name)}, start: {__MODULE__, :start_link, [opts]}}

  # -- the API ------------------------------------------------------------------------------

  @doc """
  Write `data` (a binary, or `{:file, path}` to move a file already on the
  same disk) into spool `name` as `id` (sortable; `new_id/0`), with `meta`
  (a small map kept beside it). `{:ok, entry}` or `{:error, :full | reason}`.
  Runs in the caller.
  """
  def put(name, id, data, meta \\ %{}) do
    bytes = size(data)

    with :ok <- call(name, {:reserve, bytes}),
         {:ok, dir} <- call(name, :dir) do
      try do
        final = Path.join(dir, id)
        sha = write(data, final <> ".part")
        File.rename!(final <> ".part", final)
        entry = %{id: id, bytes: bytes, sha256: sha, meta: meta, at_ms: System.os_time(:millisecond), state: :ready}
        :ok = call(name, {:commit, entry})
        {:ok, entry}
      rescue
        e ->
          call(name, {:unreserve, bytes})
          File.rm(Path.join(dir, id <> ".part"))
          {:error, Exception.message(e)}
      end
    end
  end

  @doc "A sortable, unique id: milliseconds since 1970 and a counter."
  def new_id, do: "#{System.os_time(:millisecond)}-#{System.unique_integer([:positive, :monotonic])}"

  @doc "Up to `n` files to take, oldest first: `[%{id, bytes, sha256, meta, url, path}]`, each leased."
  def lease(name, n), do: call(name, {:lease, n})

  @doc "File `id` was taken and checked: it may go when room is needed."
  def ack(name, id), do: call(name, {:ack, id})

  @doc "File `id` wasn't taken after all: offer it again."
  def release(name, id), do: call(name, {:release, id})

  @doc "Where file `id` is, for serving it."
  def path(name, id), do: call(name, {:path, id})

  defp call(name, msg) do
    GenServer.call(Queues.via(name), msg, 10_000)
  catch
    :exit, _ -> {:error, :no_spool}
  end

  # -- the process --------------------------------------------------------------------------

  @impl true
  def init(opts) do
    dir = Keyword.fetch!(opts, :dir)
    File.mkdir_p!(dir)
    Process.send_after(self(), :report, @report_ms)
    Process.send_after(self(), :tidy, @tidy_ms)

    index = Keyword.get(opts, :index, Queues.Spool.Files)
    files = load(index, opts[:name], dir)
    free = free_bytes(dir)
    used = files |> Map.values() |> Enum.map(& &1.bytes) |> Enum.sum()

    budget =
      Keyword.get_lazy(opts, :budget_bytes, fn -> if free, do: min(div(free + used, 4), @max_budget), else: @max_budget end)

    Logger.info("spool #{opts[:name]}: #{map_size(files)} files (#{mb(used)} MB) in #{dir}, budget #{mb(budget)} MB, #{mb(free || 0)} MB free")

    {:ok,
     %{
       name: Keyword.fetch!(opts, :name),
       label: Keyword.get(opts, :label, to_string(opts[:name])),
       step: Keyword.get(opts, :step, 0),
       dir: dir,
       url: Keyword.get(opts, :url),
       index: index,
       budget: budget,
       min_free: Keyword.get(opts, :min_free_bytes, 1024 * 1024 * 1024),
       lease_ms: Keyword.get(opts, :lease_ms, 60_000),
       max_leased: Keyword.get(opts, :max_leased, 2),
       max_files: Keyword.get(opts, :max_files, :infinity),
       paused: Keyword.get(opts, :paused, false),
       files: files,
       used: used,
       reserved: 0,
       free: free,
       full: false,
       meter: Meter.new(),
       counts: %{put: 0, taken: 0, deleted: 0, full: 0, expired: 0, evicted: 0},
       taken_bytes: 0
     }}
  end

  @impl true
  def handle_call(:dir, _from, s), do: {:reply, {:ok, s.dir}, s}

  def handle_call({:reserve, bytes}, _from, s) do
    s = make_room(s, bytes)

    if over?(s, bytes) do
      {:reply, {:error, :full}, %{s | full: true, counts: Map.update!(s.counts, :full, &(&1 + 1))}}
    else
      {:reply, :ok, %{s | reserved: s.reserved + bytes, full: false}}
    end
  end

  def handle_call({:unreserve, bytes}, _from, s), do: {:reply, :ok, %{s | reserved: max(s.reserved - bytes, 0)}}

  def handle_call({:commit, entry}, _from, s) do
    s.index.put(s.name, s.dir, entry)
    entry = Map.merge(entry, %{leased_until: nil, leased_at: nil})
    Telescope.broadcast("spool:#{s.name}", {:spool_ready, node(), s.name})

    s = %{
      s
      | files: Map.put(s.files, entry.id, entry),
        used: s.used + entry.bytes,
        reserved: max(s.reserved - entry.bytes, 0),
        free: s.free && s.free - entry.bytes,
        counts: Map.update!(s.counts, :put, &(&1 + 1))
    }

    {:reply, :ok, keep_newest(s)}
  end

  def handle_call({:lease, n}, _from, s) do
    s = expire(s)
    n = if paused?(s), do: 0, else: n
    now = Meter.now()
    out = Enum.count(s.files, fn {_, f} -> f.state == :leased end)

    picked =
      s.files
      |> Map.values()
      |> Enum.filter(&(&1.state == :ready))
      |> Enum.sort_by(& &1.id)
      |> Enum.take(max(min(n, s.max_leased - out), 0))

    files =
      Enum.reduce(picked, s.files, fn f, acc ->
        Map.put(acc, f.id, %{f | state: :leased, leased_at: now, leased_until: now + s.lease_ms})
      end)

    reply = Enum.map(picked, &Map.merge(Map.take(&1, [:id, :bytes, :sha256, :meta]), %{url: url(s, &1.id), path: Path.join(s.dir, &1.id)}))
    {:reply, reply, %{s | files: files}}
  end

  def handle_call({:ack, id}, _from, s) do
    case s.files[id] do
      %{state: :leased} = f ->
        now = Meter.now()
        waited = max(System.os_time(:millisecond) - f.at_ms - (now - f.leased_at), 0)
        f = %{f | state: :sent, leased_until: nil}
        s.index.update(s.name, s.dir, Map.drop(f, [:leased_at, :leased_until]))
        meter = Meter.add(s.meter, f.leased_at, now, waited, f.bytes)
        {:reply, :ok, %{s | files: Map.put(s.files, id, f), meter: meter, counts: Map.update!(s.counts, :taken, &(&1 + 1)), taken_bytes: s.taken_bytes + f.bytes}}

      %{state: :sent} ->
        {:reply, :ok, s}

      _ ->
        {:reply, {:error, :not_leased}, s}
    end
  end

  def handle_call({:release, id}, _from, s) do
    case s.files[id] do
      %{state: :leased} = f -> {:reply, :ok, %{s | files: Map.put(s.files, id, %{f | state: :ready, leased_until: nil})}}
      _ -> {:reply, :ok, s}
    end
  end

  def handle_call({:path, id}, _from, s) do
    if Map.has_key?(s.files, id), do: {:reply, {:ok, Path.join(s.dir, id)}, s}, else: {:reply, {:error, :not_found}, s}
  end

  def handle_call(:stats, _from, s), do: {:reply, stats(s), s}
  def handle_call(:room, _from, s), do: {:reply, if(over?(s, 0), do: 0, else: 1), s}

  @impl true
  def handle_info(:report, s) do
    Process.send_after(self(), :report, @report_ms)
    s = expire(s)
    Telescope.broadcast("queues", {:queue, node(), s.name, stats(s)})
    {:noreply, s}
  end

  def handle_info(:tidy, s) do
    Process.send_after(self(), :tidy, @tidy_ms)
    s = %{s | free: free_bytes(s.dir) || s.free}
    {:noreply, s |> make_room(0) |> keep_newest()}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- room --------------------------------------------------------------------------------

  defp over?(s, bytes) do
    s.used + s.reserved + bytes > s.budget or (s.free != nil and s.free - s.reserved - bytes < s.min_free)
  end

  defp paused?(%{paused: f}) when is_function(f, 0), do: f.() == true
  defp paused?(%{paused: p}), do: p == true

  defp max_files(%{max_files: f}) when is_function(f, 0), do: f.()
  defp max_files(%{max_files: n}), do: n

  # no more than max_files: the oldest go, taken ones first, then the oldest waiting (never one being copied)
  defp keep_newest(s) do
    case max_files(s) do
      n when is_integer(n) and map_size(s.files) > n ->
        # never the newest: if everything older is being copied, the limit waits for those copies
        newest = s.files |> Map.keys() |> Enum.max()
        files = s.files |> Map.values() |> Enum.reject(&(&1.id == newest))

        victim =
          files |> Enum.filter(&(&1.state == :sent)) |> Enum.min_by(& &1.id, fn -> nil end) ||
            files |> Enum.filter(&(&1.state == :ready)) |> Enum.min_by(& &1.id, fn -> nil end)

        if victim do
          File.rm(Path.join(s.dir, victim.id))
          s.index.delete(s.name, s.dir, victim.id)

          %{s | files: Map.delete(s.files, victim.id), used: s.used - victim.bytes, free: s.free && s.free + victim.bytes, counts: Map.update!(s.counts, :evicted, &(&1 + 1))}
          |> keep_newest()
        else
          s
        end

      _ ->
        s
    end
  end

  # delete taken files, oldest first, until the next `bytes` fit (or none are left to delete)
  defp make_room(s, bytes) do
    if over?(s, bytes) do
      case s.files |> Map.values() |> Enum.filter(&(&1.state == :sent)) |> Enum.min_by(& &1.id, fn -> nil end) do
        nil ->
          s

        f ->
          File.rm(Path.join(s.dir, f.id))
          s.index.delete(s.name, s.dir, f.id)

          make_room(
            %{s | files: Map.delete(s.files, f.id), used: s.used - f.bytes, free: s.free && s.free + f.bytes, counts: Map.update!(s.counts, :deleted, &(&1 + 1))},
            bytes
          )
      end
    else
      s
    end
  end

  # leases nobody acked in time: offer those files again
  defp expire(s) do
    now = Meter.now()

    {files, n} =
      Enum.reduce(s.files, {s.files, 0}, fn
        {id, %{state: :leased, leased_until: t} = f}, {acc, n} when t < now -> {Map.put(acc, id, %{f | state: :ready, leased_until: nil}), n + 1}
        _, acc -> acc
      end)

    if n > 0, do: Logger.warning("spool #{s.name}: #{n} lease(s) ran out; offering again")
    %{s | files: files, counts: Map.update!(s.counts, :expired, &(&1 + n))}
  end

  # -- disk --------------------------------------------------------------------------------

  # what was here before a restart, from the index; a half-written .part is thrown away
  defp load(index, name, dir) do
    for p <- Path.wildcard(Path.join(dir, "*.part")), do: File.rm(p)

    for %{id: id} = e <- index.load(name, dir), into: %{} do
      state = if e.state == :sent, do: :sent, else: :ready
      {id, Map.merge(e, %{state: state, leased_until: nil, leased_at: nil})}
    end
  end

  defp write(data, path) when is_binary(data) do
    File.write!(path, data)
    :crypto.hash(:sha256, data) |> Base.encode16(case: :lower)
  end

  defp write({:file, src}, path) do
    File.rename!(src, path)
    sha256_file(path)
  end

  @doc "A file's SHA-256, read in 1 MB pieces (a raw frame never sits whole in memory)."
  def sha256_file(path) do
    path
    |> File.stream!(1_048_576)
    |> Enum.reduce(:crypto.hash_init(:sha256), &:crypto.hash_update(&2, &1))
    |> :crypto.hash_final()
    |> Base.encode16(case: :lower)
  end

  defp size(data) when is_binary(data), do: byte_size(data)
  defp size({:file, path}), do: File.stat!(path).size

  # free bytes on the disk under `dir`, from df (Linux and macOS both say 1K blocks with -k)
  defp free_bytes(dir) do
    case System.cmd("df", ["-k", dir], stderr_to_stdout: true) do
      {out, 0} ->
        with [_, line | _] <- String.split(out, "\n", trim: true),
             [_, _, _, avail | _] <- String.split(line),
             {kb, _} <- Integer.parse(avail) do
          kb * 1024
        else
          _ -> nil
        end

      _ ->
        nil
    end
  rescue
    _ -> nil
  end

  defp url(%{url: nil}, _id), do: nil
  defp url(%{url: fun}, id) when is_function(fun, 1), do: fun.(id)
  defp url(%{url: {m, f, a}}, id), do: apply(m, f, a ++ [id])

  defp mb(b), do: Float.round(b / 1_048_576, 1)

  # -- numbers ------------------------------------------------------------------------------

  defp stats(s) do
    now = Meter.now()
    files = Map.values(s.files)
    waiting = Enum.filter(files, &(&1.state in [:ready, :leased]))
    leased = Enum.filter(files, &(&1.state == :leased))
    oldest = waiting |> Enum.map(& &1.at_ms) |> Enum.min(fn -> nil end)

    Map.merge(Meter.read(s.meter, Enum.map(leased, & &1.leased_at), s.max_leased, now), %{
      name: s.name,
      label: s.label,
      step: s.step,
      kind: :spool,
      depth: length(waiting),
      depth_bytes: waiting |> Enum.map(& &1.bytes) |> Enum.sum(),
      running: length(leased),
      concurrency: s.max_leased,
      oldest_wait_ms: if(oldest, do: max(System.os_time(:millisecond) - oldest, 0), else: 0),
      counts: s.counts,
      used_bytes: s.used,
      budget_bytes: s.budget,
      max_files: max_files(s),
      paused: paused?(s),
      free_bytes: s.free,
      full: s.full,
      total: s.counts.taken,
      total_bytes: s.taken_bytes,
      last_error: if(s.full, do: "full: waiting for files to be taken")
    })
  end
end
