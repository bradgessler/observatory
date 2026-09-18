import Config

# No cable plugged in? Run a simulated EQ6-R so the rest of the stack still works.
config :mount, simulate_when_empty: true
