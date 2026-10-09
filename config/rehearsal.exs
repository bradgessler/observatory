# A second copy of the app for rehearsing a night on the simulator while the
# real mount is busy on :dev — different port, no USB, no pad, its own
# settings and frame folders. Run with: MIX_ENV=rehearsal mix phx.server
import Config
import_config "dev.exs"

config :controller, Controller.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4001],
  code_reloader: false,
  live_reload: nil

config :mount, mounts: [[id: "sim-eq", transport: {Mount.Transport.Sim, []}]], simulate_when_empty: false
config :input, discover: false
config :libcluster, topologies: :none
# all simulators, so never a node of the cluster, whatever OBSERVATORY_CLUSTER says for dev
config :telescope, distribution: nil
config :controller, settings_path: "/private/tmp/claude-501/-Users-bradgessler-Projects-bradgessler-telescope/5882340a-5739-4a9c-8f7f-f174bd582638/scratchpad/rehearsal/settings.json"
config :watch, dir: "/private/tmp/claude-501/-Users-bradgessler-Projects-bradgessler-telescope/5882340a-5739-4a9c-8f7f-f174bd582638/scratchpad/rehearsal/frames"
config :video, dir: "/private/tmp/claude-501/-Users-bradgessler-Projects-bradgessler-telescope/5882340a-5739-4a9c-8f7f-f174bd582638/scratchpad/rehearsal/video"
