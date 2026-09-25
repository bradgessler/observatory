defmodule Controller.Router do
  use Controller, :router

  # Extension pages are compiled after the controller, by the apps that depend
  # on it, so they do not exist yet when this does. That is the design, not an
  # oversight.
  @compile {:no_warn_undefined, Enum.map(Controller.Extensions.routes() ++ Controller.Extensions.bare(), &elem(&1, 2))}

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {Controller.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  # Pages other apps plug in for this build (Controller.Extensions): the
  # stamping Mac's Stamp a Box, a box's Network page and captive portal. The
  # controller depends on none of them. These scopes carry no module alias,
  # since the modules are not the controller's, and they come first, because
  # the catch-all "/:id" at the end of the controller's own scope would
  # otherwise take their paths for mount ids.
  scope "/" do
    for {:get, path, plug, action} <- Controller.Extensions.bare(), do: get(path, plug, action)
  end

  scope "/" do
    pipe_through :browser

    for route <- Controller.Extensions.routes() do
      case route do
        {:live, path, view, action} -> live(path, view, action)
        {:get, path, plug, action} -> get(path, plug, action)
      end
    end
  end

  scope "/", Controller do
    pipe_through :browser

    # the front door: a grouped list of everything, one line each
    live "/", HomeLive, :index
    live "/start", StartLive, :index
    live "/start/:id", StartLive, :show
    live "/keypad", MountLive, :index
    live "/keypad/:id", MountLive, :show
    live "/sky", SkyLive, :index
    live "/object/:id", ObjectLive, :show
    live "/controls/orb", OrbLive, :index
    live "/controls/orb/:id", OrbLive, :show
    live "/events", EventsLive, :index
    live "/devices", DevicesLive, :index
    live "/devices/ports", PortsLive, :index
    live "/input", InputLive, :index
    live "/bench", BenchLive, :index
    live "/bench/:surface", BenchLive, :show
    live "/controls/eyepiece", EyepieceLive, :index
    live "/controls/eyepiece/:id", EyepieceLive, :show
    live "/controls/scope", ScopeLive, :index
    live "/controls/scope/:id", ScopeLive, :show
    live "/controls/watch", WatchLive, :index
    live "/controls/watch/frames", FramesLive, :index
    live "/controls/watch/camera", CameraLive, :index
    live "/controls/watch/axes", AxesLive, :index
    live "/controls/watch/axes/:id", AxesLive, :show
    get "/watch/latest.jpg", WatchController, :latest
    live "/controls/dpad", DpadLive, :index
    live "/controls/dpad/:id", DpadLive, :show
    live "/controls/nudge", NudgeLive, :index
    live "/controls/nudge/:id", NudgeLive, :show
    live "/controls/position", PositionLive, :index
    live "/controls/position/:id", PositionLive, :show
    live "/controls/align", LineupLive, :index
    live "/controls/align/:id", LineupLive, :show
    live "/controls/tilt", TiltLive, :index
    live "/controls/tilt/:id", TiltLive, :show
    get "/watch/frames/:name", WatchController, :frame
    get "/video/:quality/:name", VideoController, :file
    live "/setup/:id", SetupLive, :show
    live "/sky/:id", SkyLive, :show
    get "/docs/:slug", DocsController, :show
    live "/:id", MountLive, :show
  end
end
