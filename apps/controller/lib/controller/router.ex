defmodule Controller.Router do
  use Controller, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {Controller.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
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
