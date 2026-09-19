#!/bin/sh
# Runs a long-lived tool (ffmpeg) under a BEAM port. The tool must not read
# stdin (ffmpeg gets -nostdin). We hold stdin ourselves: when the port closes
# — Video.HLS stopped it, or the BEAM died — we bring the tool down: SIGINT so
# it can finish its playlist, then SIGTERM, then SIGKILL if it is still
# around. Nothing outlives us. And when the tool dies on its own we exit with
# its status at once, so the port sees an exit_status instead of a silence.
#
# stdin is read by a helper, because the main shell is busy in `wait` for the
# tool; a trapped signal interrupts `wait` in every POSIX shell. The helper
# reads through fd 3: a background job's fd 0 is /dev/null in a shell without
# job control. (Nothing here is bash-only: /bin/sh is dash or busybox on Linux.)
exec 3<&0
"$@" &
pid=$!
( while read -r _ <&3; do :; done; kill -USR1 $$ 2>/dev/null ) &
reader=$!
trap ':' USR1

wait "$pid"
status=$?
if kill -0 "$pid" 2>/dev/null; then
  # stdin closed while the tool still runs: the shutdown ladder
  kill -INT "$pid" 2>/dev/null
  i=0
  while kill -0 "$pid" 2>/dev/null && [ $i -lt 40 ]; do sleep 0.1; i=$((i + 1)); done
  kill -TERM "$pid" 2>/dev/null
  i=0
  while kill -0 "$pid" 2>/dev/null && [ $i -lt 20 ]; do sleep 0.1; i=$((i + 1)); done
  kill -KILL "$pid" 2>/dev/null
  wait "$pid"
  status=$?
fi
kill "$reader" 2>/dev/null
exit "$status"
