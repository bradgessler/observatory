# The host tools Observatory shells out to on a Mac. `brew bundle` installs them.
#
# Everything in the product path is Elixir; these are the few things the
# operating system is better at, and each one is asked for by name at the
# moment a feature needs it. A missing tool is never a crash: the page says
# what is missing and what to run, and the rest of the app keeps working.

brew "elixir"

# Building a Nerves image and writing it to an SD card (the Stamp a Box flow).
# Both are checked before the first step runs: a build that gets ten minutes in
# and then says a tool is missing has wasted the ten minutes.
brew "fwup"
brew "squashfs"

# USB game pads, read by apps/input through a small C port program linked
# against libhidapi. Without it the pad never appears; the keypad still drives
# the scope.
brew "hidapi"
brew "pkg-config"

# Video and stills from a camera. Without ffmpeg there is no live video;
# imagesnap is the Mac's way of taking a single frame.
brew "ffmpeg"
brew "imagesnap"

# Booting a built image in a VM instead of on a Pi, for the firmware tests.
brew "qemu"
