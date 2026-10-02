defmodule Queues.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Registry, keys: :unique, name: Queues.Registry},
      # the work itself: never linked to a queue, so a crash in one item is that item's
      {Task.Supervisor, name: Queues.Tasks},
      Queues.Board
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: Queues.Supervisor)
  end
end
