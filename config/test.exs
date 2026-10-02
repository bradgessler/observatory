import Config

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :controller, Controller.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "ryAW4k+yfDkYfvB9WBckY4kip0NYE1hpKYX5ON5V1QVgl9zuQdU9jhyn7AapZ1z7",
  server: false

config :mount, mounts: []
# don't fight the dev server for the real game controller during tests
config :input, discover: false
config :libcluster, topologies: []
config :logger, level: :warning

# frame history goes to a scratch dir, never the user's ~/.observatory
config :watch, dir: Path.join(System.tmp_dir!(), "observatory-test-frames-#{System.os_time(:millisecond)}")

config :controller, settings_path: Path.join(System.tmp_dir!(), "observatory-test-settings-#{System.os_time(:millisecond)}.json")
# plates (photos through the eyepiece) go to a scratch dir too
config :controller, Controller.Repo, database: Path.join(System.tmp_dir!(), "observatory-test-#{System.os_time(:millisecond)}.db")

config :controller, :frames,
  pull: true,
  dir: Path.join(System.tmp_dir!(), "observatory-test-frames-#{System.os_time(:millisecond)}"),
  spool_dir: Path.join(System.tmp_dir!(), "observatory-test-spool-#{System.os_time(:millisecond)}"),
  budget_bytes: 64 * 1024 * 1024,
  min_free_bytes: 0

config :controller, plates_dir: Path.join(System.tmp_dir!(), "observatory-test-plates-#{System.os_time(:millisecond)}")
config :video, dir: Path.join(System.tmp_dir!(), "observatory-test-video-#{System.os_time(:millisecond)}")
