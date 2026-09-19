#!/bin/sh
# Runs a long-lived tool (ffmpeg) under a BEAM port. The tool must not read
# stdin (ffmpeg gets -nostdin). We hold stdin ourselves: when the port closes
# — Video.HLS stopped it, or the BEAM died — read returns and we bring the
# tool down: SIGINT so it can finish its playlist, then SIGTERM, then SIGKILL
# if it is still around. Nothing outlives us.
"$@" &
pid=$!
while read -r _; do :; done
kill -INT "$pid" 2>/dev/null
i=0
while kill -0 "$pid" 2>/dev/null && [ $i -lt 40 ]; do sleep 0.1; i=$((i + 1)); done
kill -TERM "$pid" 2>/dev/null
i=0
while kill -0 "$pid" 2>/dev/null && [ $i -lt 20 ]; do sleep 0.1; i=$((i + 1)); done
kill -KILL "$pid" 2>/dev/null
wait "$pid"
