defmodule Telescope.Relay do
  @moduledoc """
  Sends a broadcast on to the other machines of the cluster, so the process
  that made it never has to.

  A send to another machine can put the sender to sleep: when the link is
  full (a megabyte waiting, by default) the VM suspends every process that
  sends over it until it drains. On 13 October 2026 that was the mount driver
  and the tracker: pictures were crossing the cluster to the Mac over weak
  Wi-Fi, the driver's four-a-second snapshot broadcast hit the full link, the
  driver slept for five seconds, and the dead-man stopped both motors in the
  middle of a run of exposures. A broadcast is news, not a command: the
  machine it happened on hears it at once (`Telescope.broadcast/2` delivers
  it here itself), and this process carries it to the others. If the link is
  slow it is this process that sleeps.

  It does not let a stuck link eat the box's memory: past #{2_000} broadcasts
  waiting, the oldest are dropped and the log says how many. Every status
  topic is sent again within a second, so a page elsewhere catches up.
  """
  use GenServer
  require Logger

  @pubsub Telescope.PubSub
  @most 2_000

  def start_link(_), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  @doc "Carry `message` on `topic` to every other machine. Never waits."
  def forward(topic, message) do
    if Node.list() != [], do: send(__MODULE__, {:forward, topic, message})
    :ok
  rescue
    # not started (a test of one module): there is nobody else to tell
    ArgumentError -> :ok
  end

  @impl true
  def init(_), do: {:ok, nil}

  @impl true
  def handle_info({:forward, topic, message}, s) do
    for node <- Node.list(), do: Phoenix.PubSub.direct_broadcast(node, @pubsub, topic, message)
    shed()
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp shed do
    case Process.info(self(), :message_queue_len) do
      {:message_queue_len, n} when n > @most ->
        dropped = drop(n - div(@most, 2), 0)
        Logger.warning("relay: the link to the other machines is slow; dropped #{dropped} broadcasts")

      _ ->
        :ok
    end
  end

  defp drop(0, done), do: done

  defp drop(n, done) do
    receive do
      {:forward, _, _} -> drop(n - 1, done + 1)
    after
      0 -> done
    end
  end
end
