defmodule Controller.Plates.Supervisor do
  @moduledoc """
  The plate-solving subtree: the solve workers' task supervisor and the queue
  that feeds them (`Controller.Plates`). A plate that crashes or hangs is one
  failed plate; the queue never goes down with it. If the queue itself keeps
  crashing (3 restarts in 30 s), this supervisor gives up and stops:
  the controller starts it as a transient child, so giving up is the end of
  plate solving until someone asks for it again (`Controller.Plates.restart/0`,
  the page's Restart key), never the end of the app. The mount, the keypad
  and every other page carry on.
  """
  use Supervisor

  def start_link(opts \\ []), do: Supervisor.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "How the controller's supervisor should hold this one: transient, so giving up stays given up."
  def child_spec(opts), do: %{id: __MODULE__, start: {__MODULE__, :start_link, [opts]}, type: :supervisor, restart: :transient}

  @impl true
  def init(opts) do
    children = [
      {Task.Supervisor, name: Controller.Plates.Tasks},
      {Controller.Plates, opts}
    ]

    # the queue owns its workers' results: if either goes, both start fresh
    # (plates that were solving are queued again from disk)
    Supervisor.init(children, strategy: :one_for_all, max_restarts: 3, max_seconds: 30)
  end
end
