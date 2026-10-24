import Config

config :controller,
  generators: [context_app: false],
  # What the stamping Mac plugs into the controller (Controller.Extensions): Stamp a
  # Box, from the stamp app. A stamped box lists its own extensions in
  # firmware/config/target.exs and never compiles this one.
  extensions: [
    %{
      routes: [
        {:live, "/provision", Stamp.Live, :index},
        {:live, "/provision/:step", Stamp.Live, :step}
      ],
      home: [
        {"System", {"Stamp a Box", "/provision", "Build an Observatory image and write it to an SD card", "/docs/provision", "sdcard"}}
      ]
    }
  ]

# Configures the endpoint
config :controller, Controller.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [html: Controller.ErrorHTML, json: Controller.ErrorJSON],
    layout: false
  ],
  pubsub_server: Telescope.PubSub,
  live_view: [signing_salt: "4T+tSHI9"]

# Mounts to drive. `:auto` watches USB for EQDIR cables (FTDI) and starts a
# driver per cable; a list pins them down explicitly:
#
#     config :mount, mounts: [
#       [id: "eq6r", transport: {Mount.Transport.Serial, port: "/dev/ttyUSB0"}]
#     ]
config :mount,
  mounts: :auto,
  simulate_when_empty: false,
  # Soft limits, degrees from home (counterweight down, scope at the pole).
  # Armed by Mount.set_home/1; a slew that reaches one is stopped there.
  # RA: past ±100° the counterweight is above the mount and the tube is heading
  # for the tripod. Dec: a full swing either way is legitimate on a GEM (that's
  # how the "other side of the pier" works), so only guard against wrap-around.
  limits: %{ra: {-100.0, 100.0}, dec: {-175.0, 175.0}}

# The database (Controller.Repo): SQLite, ~/.observatory/observatory.db unless set
config :controller, ecto_repos: [Controller.Repo]
config :controller, Controller.Repo, journal_mode: :wal, pool_size: 5, busy_timeout: 5_000

# Nodes on the same LAN find each other by multicast, where an environment
# lets them: dev only when started with OBSERVATORY_CLUSTER=1 (config/dev.exs),
# test and rehearsal never. An environment switches this off with
# `topologies: :none`, not `[]`: an empty list merges into this one and
# changes nothing.
config :libcluster,
  topologies: [lan: [strategy: Cluster.Strategy.Gossip]]

config :logger, :default_formatter, format: "$time $metadata[$level] $message\n"

# Never print these in a log. "keys" is what the in-page terminal sends: every
# keystroke, a sudo password among them.
config :phoenix, :filter_parameters, ["password", "keys"]

import_config "#{config_env()}.exs"

config :controller,
  # First-order pointing model for the sky map (axis degrees from home → sky).
  # Signs are a guess until verified on a star; plate solving replaces this.
  pointing: %{ha_sign: 1, dec_sign: -1}

# Where the scope is (the sky map's alt/az and sidereal time, and the blog's privacy check). The repository is
# public, so it is never written here: config/site.secret.exs on the machine that builds (git ignores it; the
# firmware built there carries it), else OBSERVATORY_SITE="lat,lon,name" (the blog's CI, from a repository
# secret). Without either the site comes from the box's settings (typed, or from a phone), else 0°, 0°, said so.
cond do
  File.exists?(Path.join(__DIR__, "site.secret.exs")) ->
    import_config "site.secret.exs"

  # an unset repository secret arrives as an empty string: no site, not a crash
  (site = System.get_env("OBSERVATORY_SITE")) not in [nil, ""] ->
    [lat, lon | name] = String.split(site, ",", parts: 3)
    config :controller, site: %{lat: String.to_float(String.trim(lat)), lon: String.to_float(String.trim(lon)), name: name |> Enum.join() |> String.trim()}

  true ->
    :ok
end

