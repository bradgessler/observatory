#!/bin/sh
# Build the box's firmware from this checkout. Prints only the result: the stamp file it reads
# holds the Wi-Fi passwords, and they must never reach a terminal or a log.
set -e
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT/firmware"
eval "$(grep '^export ' "$HOME/.observatory/stamps/observatory-rpi3.sh")"
LOG=$(mktemp)
if (mix deps.get && mix firmware) > "$LOG" 2>&1; then
  FW="$ROOT/firmware/_build/rpi3_prod/nerves/images/firmware.fw"
  # a Mac binary in the Pi's image is a camera that is silently off
  for bin in camera/priv/usbport; do
    file "$ROOT/firmware/_build/rpi3_prod/lib/$bin" | grep -q "ELF 32-bit.*ARM" || { echo "NOT BUILT FOR THE PI: $bin"; exit 1; }
  done
  echo "built $(ls -l "$FW" | awk '{print $5}') bytes: $FW"
else
  grep -aE "error|\*\*" "$LOG" | head -20
  echo "build failed: $LOG"
  exit 1
fi
