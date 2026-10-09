defmodule Controller.Frames.Pull do
  @moduledoc """
  On the Mac: takes frames from every box's spool as fast as `frames.fetch`
  has room for them, and no faster. It leases a few at a time over the
  cluster (a small message), hands each lease to `frames.fetch`, and gives
  back any lease the queue couldn't take. It wakes when a spool says it has
  something (`"spool:frames"`) and every second regardless.

  The demand comes from here, so a busy Mac never has frames pushed at it:
  they wait on the box's card, which is what the card's budget is for.
  """
  use GenServer

  alias Controller.Frames
  alias Queues.Spool

  @every_ms 1_000
  @batch 4

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_) do
    Telescope.subscribe("spool:frames")
    send(self(), :pull)
    {:ok, %{}}
  end

  @impl true
  def handle_info(:pull, s) do
    Process.send_after(self(), :pull, @every_ms)
    if Frames.copying?(), do: pull()
    {:noreply, s}
  end

  def handle_info({:spool_ready, _node, _name}, s) do
    if Frames.copying?(), do: pull()
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp pull do
    for node <- [node() | Node.list()] do
      room = Queues.room("frames.fetch")

      if room > 0 do
        case Frames.remote(node, Spool, :lease, ["frames", min(room, @batch)]) do
          leases when is_list(leases) ->
            for l <- leases do
              case Queues.push("frames.fetch", Map.put(l, :node, node), bytes: l.bytes) do
                :ok -> :ok
                _ -> Frames.remote(node, Spool, :release, ["frames", l.id])
              end
            end

          # no spool there (a Mac without a camera, an older box): nothing to take
          _ ->
            :ok
        end
      end
    end
  end
end
