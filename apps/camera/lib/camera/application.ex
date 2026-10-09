defmodule Camera.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Registry, keys: :unique, name: Camera.Registry},
      # a camera's process ends on any failure; Camera.Discovery decides whether to start it again
      {DynamicSupervisor,
       name: Camera.Supervisor, strategy: :one_for_one, max_restarts: 1_000, max_seconds: 1},
      Camera.Discovery
    ]

    Supervisor.start_link(children, strategy: :rest_for_one, name: Camera.TopSupervisor)
  end
end
