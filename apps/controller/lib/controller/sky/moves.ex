defmodule Controller.Sky.Moves do
  @moduledoc """
  Moves that go in legs, with a person checking in between.

  A meridian flip swings the tube from one side of the pier to the other. The
  risky part is the end, when the tube comes down toward the target on the
  new side, past legs and cables nobody has looked at yet. So a flip goes in
  two legs: first home (counterweight straight down, tube at the pole: the
  most compact pose the mount has), where it stops and asks; then, once
  someone says the way is clear, on to the target.

  The pending move is the telescope's state, not a page's: every phone sees
  "home, halfway to the Moon: is the way clear?" and any of them can answer.
  STOP anywhere cancels it. Broadcasts `{:move, id, pending | nil}` on
  `"moves"`.

      Moves.flip(mount_id, obj)   # leg 1: home
      Moves.pending(mount_id)     # nil | %{obj, leg: :home | :waiting, since}
      Moves.continue(mount_id)    # leg 2: Go To with flip: true
      Moves.cancel(mount_id)
  """
  use GenServer

  alias Controller.Sky.Pointing

  @tick_ms 500

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Start a two-leg flip to `obj` on mount `id`: returns `{:ok, :home}` once leg 1 is under way."
  def flip(id, obj, opts \\ []), do: call({:flip, id, obj, opts})

  @doc "The way is clear: leg 2, on to the target. Returns what `Pointing.slew/5` returns."
  def continue(id), do: call({:continue, id})

  def cancel(id), do: call({:cancel, id})

  def pending(id), do: :persistent_term.get({__MODULE__, id}, nil)

  defp call(msg) do
    GenServer.call(__MODULE__, msg, 15_000)
  catch
    :exit, _ -> {:error, :unreachable}
  end

  @impl true
  def init(_) do
    :timer.send_interval(@tick_ms, :tick)
    {:ok, %{}}
  end

  @impl true
  def handle_call({:flip, id, obj, opts}, _from, s) do
    with {:ok, ref, snap} <- mount(id),
         ctx = Pointing.context(DateTime.utc_now(), id),
         {:ok, _, _} <- Pointing.home_leg(ref, snap, ctx) do
      Telescope.Events.emit(:move, :flip_home, %{id: id, target: obj.name})

      move = %{
        obj: obj,
        leg: :home,
        since: DateTime.utc_now(),
        started_ms: System.monotonic_time(:millisecond),
        # the last STOP before this move: any other one cancels it
        estop0: snap[:estop_at],
        opts: opts
      }

      {:reply, {:ok, :home}, put(s, id, move)}
    else
      err -> {:reply, err, s}
    end
  end

  def handle_call({:continue, id}, _from, s) do
    with %{obj: obj, opts: opts} <- s[id],
         {:ok, ref, snap} <- mount(id) do
      ctx = Pointing.context(DateTime.utc_now(), id)
      reply = Pointing.slew(ref, snap, obj, ctx, Keyword.merge(opts, flip: true))

      if match?({:ok, _, _}, reply),
        do: Telescope.Events.emit(:move, :flip_on, %{id: id, target: obj.name})

      {:reply, reply, put(s, id, nil)}
    else
      nil -> {:reply, {:error, :nothing_pending}, s}
      err -> {:reply, err, s}
    end
  end

  def handle_call({:cancel, id}, _from, s), do: {:reply, :ok, put(s, id, nil)}

  # leg 1 landed: wait for a person. STOP anywhere: forget the whole move.
  @impl true
  def handle_info(:tick, s) do
    s =
      Enum.reduce(s, s, fn {id, move}, acc ->
        case mount(id) do
          {:ok, _ref, snap} ->
            cond do
              is_integer(snap[:estop_at]) and snap.estop_at != move[:estop0] -> put(acc, id, nil)
              move.leg == :home and not moving?(snap) -> put(acc, id, %{move | leg: :waiting})
              true -> acc
            end

          _ ->
            put(acc, id, nil)
        end
      end)

    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp moving?(snap),
    do: Enum.any?(snap.axes, fn {_, ax} -> ax.running or Map.get(ax, :goto_pending, false) end)

  defp put(s, id, nil) do
    if Map.has_key?(s, id) do
      :persistent_term.erase({__MODULE__, id})
      Telescope.broadcast("moves", {:move, id, nil})
    end

    Map.delete(s, id)
  end

  defp put(s, id, move) do
    public = Map.take(move, [:obj, :leg, :since])
    :persistent_term.put({__MODULE__, id}, public)
    Telescope.broadcast("moves", {:move, id, public})
    Map.put(s, id, move)
  end

  defp mount(id) do
    with ref when not is_nil(ref) <- Enum.find(Mount.list(), &(&1.id == id)),
         %{connected: true} = snap <- Mount.snapshot(ref) do
      {:ok, ref, snap}
    else
      _ -> {:error, :not_connected}
    end
  catch
    :exit, _ -> {:error, :not_connected}
  end
end
