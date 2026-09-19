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

    # Devices heartbeat 5×/s, so a transient fault can hit a child several
    # times a second; give it room before giving up on the whole app.
    Supervisor.start_link(children, strategy: :rest_for_one, name: Input.Supervisor, max_restarts: 10, max_seconds: 5)
  end
end
