# The VM smoke test boots a real image in qemu: opt in with --only vm
ExUnit.start(exclude: [:vm])
