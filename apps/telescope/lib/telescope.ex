defmodule Telescope do
  @moduledoc """
  Shared plumbing for every node in the observatory cluster.

  Every app (mount driver, web UI, later cameras/plate-solving) runs on the same
  `Telescope.PubSub`, so a process anywhere in the cluster can subscribe to a
  topic and receive plain Elixir terms — no serialization layer to maintain.
  """

  @pubsub Telescope.PubSub

  def subscribe(topic), do: Phoenix.PubSub.subscribe(@pubsub, topic)
  def unsubscribe(topic), do: Phoenix.PubSub.unsubscribe(@pubsub, topic)
  def broadcast(topic, message), do: Phoenix.PubSub.broadcast(@pubsub, topic, message)

  @doc """
  To subscribers on this machine only. For what belongs to the machine it
  happens on: a game pad is plugged into one machine, and its reports and its
  mapper must not reach another's (two mappers hearing one pad would both
  drive the scope, and each page would flicker between their states).
  """
  def local_broadcast(topic, message), do: Phoenix.PubSub.local_broadcast(@pubsub, topic, message)

  @doc "All connected nodes, this one first."
  def nodes, do: [node() | Node.list()]
end
