import Config

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :controller, Controller.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "ryAW4k+yfDkYfvB9WBckY4kip0NYE1hpKYX5ON5V1QVgl9zuQdU9jhyn7AapZ1z7",
  server: false

config :mount, mounts: []
config :libcluster, topologies: []
config :logger, level: :warning
