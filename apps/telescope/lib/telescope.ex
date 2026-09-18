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

  @doc "All connected nodes, this one first."
  def nodes, do: [node() | Node.list()]
end
