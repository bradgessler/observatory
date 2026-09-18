import Config

# Mounts to drive. `:auto` watches USB for EQDIR cables (FTDI) and starts a
# driver per cable; a list pins them down explicitly:
#
#     config :mount, mounts: [
#       [id: "eq6r", transport: {Mount.Transport.Serial, port: "/dev/ttyUSB0"}]
#     ]
config :mount,
  mounts: :auto,
  simulate_when_empty: false

# Nodes on the same LAN find each other by multicast; nothing to configure.
config :libcluster,
  topologies: [lan: [strategy: Cluster.Strategy.Gossip]]

config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n"

import_config "#{config_env()}.exs"
