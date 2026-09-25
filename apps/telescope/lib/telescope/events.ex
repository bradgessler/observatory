defmodule Telescope.Events do
  @moduledoc """
  What happened, in order, with who did it: one ring of recent events any
  app can append to and any page or agent can read. The first answer to
  "why is the scope pointing there?" — a hand on the pad, a page, the
  tracker, or nobody (which means it was moved by hand, power off).

      Telescope.Events.emit(:mount, :goto, %{id: "eq6r", axis: :ra, degrees: 5.0})
      Telescope.Events.recent(50)      # newest first
      Telescope.Events.subscribe()     # {:event, event} as they happen

  Each event carries `at` (UTC), `node`, `module`, `name`, `by` (the source:
  set with `Telescope.Events.tag/1` in the emitting process, e.g. the page or
  device name), and `data`. The last #{500} are kept in memory. With
  `config :telescope, events_file: path` (a box sets it) each event is also
  appended to that file and synced as it happens, and the file is read back at
  start: a box that resets mid-slew comes back up showing what led to it,
  instead of an empty list. The outward feed is #50.
  """
  use GenServer

  @keep 500
  @topic "events"

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Name the source for everything this process emits from now on."
  def tag(source), do: Process.put(:observatory_source, source)

  @doc "The source this process emits as."
  def source, do: Process.get(:observatory_source) || "unknown"

  @doc "Record an event. Never blocks the caller for long; a missing store is ignored."
  def emit(module, name, data \\ %{}) when is_atom(module) and is_atom(name) do
    event = %{at: DateTime.utc_now(), node: node(), module: module, name: name, by: source(), data: data}

    try do
      GenServer.cast(__MODULE__, {:emit, event})
    catch
      _, _ -> :ok
    end

    :ok
  end

  @doc "Newest first. `module:` filters."
  def recent(limit \\ 100, opts \\ []) do
    try do
      GenServer.call(__MODULE__, {:recent, limit, opts[:module]})
    catch
      :exit, _ -> []
    end
  end

  def subscribe, do: Telescope.subscribe(@topic)

  @impl true
  def init(_) do
    path = Application.get_env(:telescope, :events_file)
    restored = if path, do: restore(path), else: []
    {:ok, %{q: :queue.from_list(restored), io: open(path)}}
  end

  @impl true
  def handle_cast({:emit, event}, state) do
    q = :queue.in(event, state.q)
    q = if :queue.len(q) > @keep, do: elem(:queue.out(q), 1), else: q
    persist(state.io, event)
    Telescope.broadcast(@topic, {:event, event})
    {:noreply, %{state | q: q}}
  end

  @impl true
  def handle_call({:recent, limit, module}, _from, state) do
    list = state.q |> :queue.to_list() |> Enum.reverse()
    list = if module, do: Enum.filter(list, &(&1.module == module)), else: list
    {:reply, Enum.take(list, limit), state}
  end

  # -- the file: one event per line, synced, so a reset loses at most the one
  # being written. Read back at start; rewritten to the last @keep when large.

  @max_bytes 2_000_000

  defp restore(path) do
    events =
      case File.read(path) do
        {:ok, text} ->
          text
          |> String.split("\n", trim: true)
          |> Enum.take(-@keep)
          |> Enum.flat_map(&decode/1)

        _ ->
          []
      end

    if match?({:ok, %{size: size}} when size > @max_bytes, File.stat(path)) do
      File.write(path, Enum.map(events, &(encode(&1) <> "\n")))
    end

    events
  end

  defp open(nil), do: nil

  defp open(path) do
    File.mkdir_p(Path.dirname(path))

    case File.open(path, [:append, :binary, :raw]) do
      {:ok, io} -> io
      _ -> nil
    end
  end

  defp persist(nil, _), do: :ok

  defp persist(io, event) do
    _ = :file.write(io, encode(event) <> "\n")
    _ = :file.datasync(io)
    :ok
  end

  defp encode(event), do: event |> :erlang.term_to_binary() |> Base.encode64()

  defp decode(line) do
    [line |> Base.decode64!() |> :erlang.binary_to_term([:safe])]
  rescue
    _ -> []
  end
end
