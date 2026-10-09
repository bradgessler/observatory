defmodule Controller.ScopeCamera.Supervisor do
  @moduledoc """
  The telescope camera's subtree: the task supervisor its frames are taken
  under, the camera (`Controller.ScopeCamera`), and the loop that uses it to
  find where the telescope points (`Controller.AutoAlign`). A frame that
  crashes or hangs is one failed frame. If the camera itself keeps crashing
  (3 restarts in 30 s), this supervisor gives up and stops: it's a transient
  child of the controller, so the mount, the pad and every other page carry
  on without a camera.
  """
  use Supervisor

  def start_link(opts \\ []), do: Supervisor.start_link(__MODULE__, opts, name: __MODULE__)

  def child_spec(opts), do: %{id: __MODULE__, start: {__MODULE__, :start_link, [opts]}, type: :supervisor, restart: :transient}

  @impl true
  def init(opts) do
    children = [
      {Task.Supervisor, name: Controller.ScopeCamera.Tasks},
      # the camera kept open: frames as they come, one ffmpeg
      Controller.ScopeCamera.Stream,
      {Controller.ScopeCamera, opts},
      Controller.AutoAlign
    ]

    Supervisor.init(children, strategy: :one_for_all, max_restarts: 3, max_seconds: 30)
  end
end
