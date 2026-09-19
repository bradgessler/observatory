import Config

config :controller,
  generators: [context_app: false]

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
  limits: %{ra: {-100.0, 100.0}, dec: {-95.0, 95.0}}

# Nodes on the same LAN find each other by multicast; nothing to configure.
config :libcluster,
  topologies: [lan: [strategy: Cluster.Strategy.Gossip]]

config :logger, :default_formatter, format: "$time $metadata[$level] $message\n"

import_config "#{config_env()}.exs"
