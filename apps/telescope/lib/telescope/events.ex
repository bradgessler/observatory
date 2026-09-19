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
  device name), and `data`. In memory only, last #{500}; persistence and the
  outward feed are #50.
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
  def init(_), do: {:ok, :queue.new()}

  @impl true
  def handle_cast({:emit, event}, q) do
    q = :queue.in(event, q)
    q = if :queue.len(q) > @keep, do: elem(:queue.out(q), 1), else: q
    Telescope.broadcast(@topic, {:event, event})
    {:noreply, q}
  end

  @impl true
  def handle_call({:recent, limit, module}, _from, q) do
    list = q |> :queue.to_list() |> Enum.reverse()
    list = if module, do: Enum.filter(list, &(&1.module == module)), else: list
    {:reply, Enum.take(list, limit), q}
  end
end
