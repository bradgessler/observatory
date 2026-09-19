defmodule Input.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Registry, keys: :unique, name: Input.Registry},
      {DynamicSupervisor, name: Input.DeviceSupervisor, strategy: :one_for_one},
      Input.Discovery,
      Input.Mapper
    ]

    Supervisor.start_link(children, strategy: :rest_for_one, name: Input.Supervisor)
  end
end
