#!/bin/sh
# Runs a long-lived tool (ffmpeg) under a BEAM port. The tool must not read
# stdin (ffmpeg gets -nostdin). We hold stdin ourselves: when the port closes
# — Video.HLS stopped it, or the BEAM died — read returns and we send the
# tool SIGINT so it finishes its playlist and exits. Nothing outlives us.
"$@" &
pid=$!
while read -r _; do :; done
kill -INT "$pid" 2>/dev/null
wait "$pid"
