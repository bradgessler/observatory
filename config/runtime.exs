import Config

# MOUNT_PORT=/dev/ttyUSB0 pins the driver to one serial port instead of scanning.
if port = System.get_env("MOUNT_PORT") do
  config :mount,
    mounts: [[id: Path.basename(port), transport: {Mount.Transport.Serial, port: port}]]
end
