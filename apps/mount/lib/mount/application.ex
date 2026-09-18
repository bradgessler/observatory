defmodule Mount.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Registry, keys: :unique, name: Mount.Registry},
      {DynamicSupervisor, name: Mount.Supervisor, strategy: :one_for_one},
      Mount.Discovery
    ]

    Supervisor.start_link(children, strategy: :rest_for_one, name: Mount.TopSupervisor)
  end
end
