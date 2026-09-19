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

    live "/", MountLive, :index
    live "/sky", SkyLive, :index
    live "/object/:id", ObjectLive, :show
    live "/devices", DevicesLive, :index
    live "/setup/:id", SetupLive, :show
    live "/sky/:id", SkyLive, :show
    get "/docs/:slug", DocsController, :show
    live "/:id", MountLive, :show
  end
end
