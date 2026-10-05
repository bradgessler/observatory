defmodule Controller.Application do
  # See https://hexdocs.pm/elixir/Application.html
  # for more information on OTP Applications
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      Controller.Telemetry,
      # Start a worker by calling: Controller.Worker.start_link(arg)
      # {Controller.Worker, arg},
      # Start to serve requests, typically the last entry
      Controller.Sky.Catalog,
      # the database: its own branch, never waited on; settings fall back to settings.json without it
      Controller.Repo.Supervisor,
      Controller.Settings,
      # one viewer's own conveniences (the time they set the sky to): Controller.Viewer
      Controller.Viewer,
      Controller.Sky.Tracker,
      Controller.Sky.Moves,
      # the pad's (or the Center page's) Centered becomes an alignment point on the held target
      Controller.CenterPoints,
      # each telescope's alignment, kept current and said when it changes; its own branch,
      # left down (never restarting the app) if it keeps crashing
      Supervisor.child_spec(Controller.Alignment.Supervisor, restart: :temporary),
      # the pad's hat in eyepiece terms, with the Center page's map
      Controller.PadView,
      # when each mount was last switched on: a never-zeroed alignment holds until then
      Controller.MountPower,
      # the box's own supply: dips drop the USB hub, camera and mount cable with it
      Controller.Power,
      # the last word from each control layer, for a Control Stack page opening mid-session
      Controller.Stack.Memory,
      # Solve.solve/2's own tasks: a crash or a hang comes back as an error
      {Task.Supervisor, name: Controller.Sky.Solve.Tasks},
      # photos queued and plate-solved in the background; gives up alone
      Controller.Plates.Supervisor,
      # frames kept: the box's card, then the Mac; before the camera that feeds it
      Controller.Frames.Supervisor,
      # the camera in the telescope's focuser, and the loop that finds where it points
      Controller.ScopeCamera.Supervisor,
      Controller.Optical.AxisScan,
      # the stills camera (a Sony in PC Remote): pictures kept whole, measured, fed to Lock On
      Supervisor.child_spec(Controller.StillCamera.Supervisor, restart: :temporary),
      # Lock On: both motors steered from the camera; its own branch, left down if it keeps crashing
      Supervisor.child_spec(Controller.LockOn.Supervisor, restart: :temporary),
      Controller.Endpoint
    ]

    # See https://hexdocs.pm/elixir/Supervisor.html
    # for other strategies and supported options
    opts = [strategy: :one_for_one, name: Controller.Supervisor]
    Supervisor.start_link(children, opts)
  end

  # Tell Phoenix to update the endpoint configuration
  # whenever the application is updated.
  @impl true
  def config_change(changed, _new, removed) do
    Controller.Endpoint.config_change(changed, removed)
    :ok
  end
end
