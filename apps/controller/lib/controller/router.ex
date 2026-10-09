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
    # who's looking: one viewer's own conveniences follow them page to page (Controller.Viewer)
    plug Controller.Viewer
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
    live "/alignment", StartLive, :index
    live "/alignment/:id", StartLive, :show
    get "/start", RedirectController, :moved, assigns: %{to: "/alignment"}
    get "/start/*rest", RedirectController, :moved, assigns: %{to: "/alignment"}
    live "/keypad", MountLive, :index
    live "/keypad/:id", MountLive, :show
    live "/sky", SkyLive, :index
    live "/tonight", SkyLive, :tonight
    # where the scope stands and what time it is, from the phone
    live "/location", SiteLive, :index
    get "/site", RedirectController, :moved, assigns: %{to: "/location"}
    live "/object/:id", ObjectLive, :show
    live "/controls/orb", OrbLive, :index
    live "/controls/orb/:id", OrbLive, :show
    live "/events", EventsLive, :index
    live "/devices", DevicesLive, :index
    live "/search", SearchLive, :index
    live "/queues", QueuesLive, :index
    live "/devices/ports", PortsLive, :index
    live "/devices/boxes", BoxesLive, :index
    live "/devices/mount/:id", MountDeviceLive, :show
    live "/input", InputLive, :index
    # the bench was a second set of pages inside these; every page has one address now
    get "/bench", RedirectController, :bench
    get "/bench/:surface", RedirectController, :bench
    live "/controls/eyepiece", EyepieceLive, :index
    live "/controls/eyepiece/:id", EyepieceLive, :show
    live "/controls/scope", ScopeLive, :index
    live "/controls/scope/:id", ScopeLive, :show
    # the cameras moved under /cameras: old links still land
    get "/controls/watch", RedirectController, :moved, assigns: %{to: "/cameras/observatory"}
    get "/controls/watch/frames", RedirectController, :moved, assigns: %{to: "/cameras/observatory/frames"}
    get "/controls/watch/camera", RedirectController, :moved, assigns: %{to: "/cameras/observatory/settings"}
    live "/controls/watch/axes", AxesLive, :index
    live "/controls/watch/axes/:id", AxesLive, :show
    get "/watch/latest.jpg", WatchController, :latest
    live "/controls/dpad", DpadLive, :index
    live "/controls/dpad/:id", DpadLive, :show
    live "/controls/nudge", NudgeLive, :index
    live "/controls/nudge/:id", NudgeLive, :show
    live "/controls/center", CenterLive, :index
    live "/stack", StackLive, :index
    live "/stack/:id", StackLive, :show
    live "/stack/:id/:term", StackLive, :term
    live "/controls/center/:id", CenterLive, :show
    live "/controls/position", PositionLive, :index
    live "/controls/position/:id", PositionLive, :show
    live "/controls/align", LineupLive, :index
    live "/controls/align/:id", LineupLive, :show
    # photos through the eyepiece, plate-solved: the polar axis and GoTo from them
    live "/align/photo", AlignPhotoLive, :index
    live "/align/photo/:id", AlignPhotoLive, :show
    # every camera in one place: the telescope camera (in the focuser) and the
    # observatory camera (watching the mount), side by side at /cameras
    live "/cameras", CamerasLive, :index
    # a kept frame waiting on this machine's card, for the Mac to copy (Controller.Frames)
    get "/spool/:name/:id", SpoolController, :show
    # the images first: "/cameras/telescope/:id" would take "frame.png" for a mount
    get "/cameras/telescope/frame.png", ScopeCameraController, :frame
    get "/cameras/telescope/frames/:seq/frame.png", ScopeCameraController, :numbered
    live "/cameras/telescope/focus", ScopeCameraFocusLive, :index
    live "/cameras/telescope/settings", ScopeCameraSettingsLive, :index
    live "/cameras/telescope/frames", ScopeCameraFramesLive, :index
    live "/cameras/telescope/frames/:seq", ScopeCameraFramesLive, :show
    live "/cameras/telescope", ScopeCameraLive, :index
    live "/cameras/telescope/:id", ScopeCameraLive, :show
    # the stills camera (a Sony in PC Remote): its last picture, the pictures kept (how they leave the box), then its page
    # the box's own record of coming back after a restart (boots, locks picked up): JSON, newest last
    get "/recoveries.json", RecoveryController, :index
    get "/cameras/stills/latest.png", StillCameraController, :latest
    get "/cameras/stills/files", StillCameraController, :nights
    get "/cameras/stills/files/:night", StillCameraController, :night
    get "/cameras/stills/files/:night/:name", StillCameraController, :file
    live "/cameras/stills", StillCameraLive, :index
    live "/cameras/observatory", WatchLive, :index
    live "/cameras/observatory/frames", FramesLive, :index
    live "/cameras/observatory/settings", CameraLive, :index
    get "/scope-camera", RedirectController, :moved, assigns: %{to: "/cameras/telescope"}
    get "/scope-camera/*rest", RedirectController, :moved, assigns: %{to: "/cameras/telescope"}
    get "/watch/frames/:name", WatchController, :frame
    get "/video/:quality/:name", VideoController, :file
    live "/setup/:id", SetupLive, :show
    live "/sky/:id", SkyLive, :show
    live "/tonight/:id", SkyLive, :tonight
    get "/docs/site", RedirectController, :moved, assigns: %{to: "/docs/location"}
    get "/docs/:slug", DocsController, :show
    # STOP from a page without a LiveView (a help page)
    post "/stop", StopController, :stop
    # the telescope switcher: which scope this viewer drives
    get "/telescope/:id", TelescopeController, :use
    live "/:id", MountLive, :show
  end
end
