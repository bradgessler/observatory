defmodule Watch.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [Watch.History, Watch.Camera]
    Supervisor.start_link(children, strategy: :one_for_one, name: Watch.Supervisor)
  end
end
