#!/bin/sh
# Watch the box's card while pictures are being taken. Says nothing while all is well; exits with a
# line the moment room runs low or the offload stops making progress, so whoever is driving hears about it.
#   storage-watch.sh <offload log> [room floor in pictures, default 60]
HERE=$(cd "$(dirname "$0")" && pwd); LOG=$1; FLOOR=${2:-60}; last=""; stale=0
while :; do
  room=$(timeout 20 "$HERE/box" 'st = Controller.StillCamera.status(); IO.puts("ROOM=#{st[:room_for]} FREE=#{st[:free_mb]} SHOOTING=#{st.shooting}")' 2>/dev/null | tr -d '\r' | grep -o 'ROOM=.*')
  n=$(echo "$room" | sed -n 's/ROOM=\([0-9]*\).*/\1/p')
  if [ -n "$n" ] && [ "$n" -lt "$FLOOR" ]; then echo "$(date -u +%H:%M:%S) LOW: the card has room for $n pictures ($room)"; exit 2; fi
  now=$(tail -1 "$LOG" 2>/dev/null)
  case "$room" in *"SHOOTING=true"*) if [ "$now" = "$last" ]; then stale=$((stale + 1)); else stale=0; fi;; *) stale=0;; esac
  last="$now"
  [ $stale -ge 10 ] && { echo "$(date -u +%H:%M:%S) STALLED: pictures are being taken but the offload has moved nothing for 10 minutes ($room); last line: $now"; exit 3; }
  pgrep -f "offload.py" >/dev/null || { echo "$(date -u +%H:%M:%S) the offload is not running ($room)"; exit 4; }
  sleep 60
done
