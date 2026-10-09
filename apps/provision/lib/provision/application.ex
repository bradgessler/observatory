defmodule Provision.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [Provision.Job, Provision.Terminal]
    Supervisor.start_link(children, strategy: :one_for_one, name: Provision.Supervisor)
  end
end
