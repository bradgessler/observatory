defmodule Telescope.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    topologies = Application.get_env(:libcluster, :topologies, [])

    children = [
      {Phoenix.PubSub, name: Telescope.PubSub},
      {Cluster.Supervisor, [topologies, [name: Telescope.ClusterSupervisor]]}
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: Telescope.Supervisor)
  end
end
