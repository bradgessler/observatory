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

    # the bench is the front door while we're playing with components
    live "/", BenchLive, :index
    live "/keypad", MountLive, :index
    live "/keypad/:id", MountLive, :show
    live "/sky", SkyLive, :index
    live "/object/:id", ObjectLive, :show
    live "/controls/orb", OrbLive, :index
    live "/controls/orb/:id", OrbLive, :show
    live "/devices", DevicesLive, :index
    live "/input", InputLive, :index
    live "/bench", BenchLive, :index
    live "/bench/:surface", BenchLive, :show
    live "/controls/watch", WatchLive, :index
    live "/controls/watch/frames", FramesLive, :index
    get "/watch/latest.jpg", WatchController, :latest
    live "/controls/dpad", DpadLive, :index
    live "/controls/dpad/:id", DpadLive, :show
    live "/controls/nudge", NudgeLive, :index
    live "/controls/nudge/:id", NudgeLive, :show
    live "/controls/position", PositionLive, :index
    live "/controls/position/:id", PositionLive, :show
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
