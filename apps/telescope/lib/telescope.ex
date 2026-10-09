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

  @doc """
  A device's news, to every machine that lists the device (`listed?/3`): the
  whole cluster for a real one, this machine alone with `simulated: true`.
  The device says which it is each time: a camera is the simulator only
  until a real one is plugged in.

      Telescope.broadcast("scope_camera", {:scope_camera, status}, simulated: status.sim)
  """
  def broadcast(topic, message, opts) do
    if opts[:simulated] == true, do: local_broadcast(topic, message), else: broadcast(topic, message)
  end

  @doc """
  Is a device that runs on `owner` listed on `here` (this machine)? A real
  one is, wherever it is in the cluster. A simulated one is listed only on
  the node that runs it.

  A simulator stands in for hardware on the machine running it (a Mac with
  nothing plugged in) and means nothing anywhere else. A Mac's simulated
  mount, listed on a box joined to that Mac, became the box's default, and
  the box's own keypad drove it while the real telescope sat still. A Mac's
  simulated telescope camera, on a box with no camera of its own, showed
  there as live frames of 24 stars, and its owner tried to focus on them.

  So this is the one rule, and every list of devices goes through it: the
  mounts (`Mount.listed?/2`), the telescope camera
  (`Controller.ScopeCamera.listed?/2`), the stills camera
  (`Controller.StillCamera.listed?/2`). A device says for itself whether it
  is simulated; where it may be seen is decided here.

      Telescope.listed?(:"observatory@mac.local", true, :"telescope@observatory.local")
      #=> false
  """
  def listed?(owner, simulated?, here \\ node()), do: owner == here or simulated? != true

  @doc "All connected nodes, this one first."
  def nodes, do: [node() | Node.list()]
end
