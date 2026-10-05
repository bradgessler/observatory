#!/bin/sh
# One outage, timed. Checks what the box is doing, flashes it, watches it come back, and writes the
# timings to ~/.observatory/outages.jsonl.
#   flash.sh "why this flash"        (BOX=10.0.1.44 by default)
# Refuses while a goto or an auto-align is in flight, and when a lock is holding without a fresh
# heartbeat (it would not be picked up).
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../../.." && pwd)
FW="$ROOT/firmware/_build/rpi3_prod/nerves/images/firmware.fw"; BOXIP=${BOX:-10.0.1.44}
KEY="-i $HOME/.observatory/vm_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
WHY=${1:-"no reason given"}
log() { echo "$(date -u +%H:%M:%S) $*"; }
field() { echo "$1" | tr ' ' '\n' | grep "^$2=" | cut -d= -f2-; }

before=$(timeout 30 "$HERE/box" - < "$HERE/before.exs" 2>/dev/null | tr -d '\r' | grep -o 'B .*' | cut -c3-)
[ -n "$before" ] || { log "the box did not answer: nothing flashed"; exit 1; }
log "before: $before"
[ "$(field "$before" busy)" = "false" ] || { log "a goto or an auto-align is in flight: not flashing"; exit 1; }
lock=$(field "$before" lock); age=$(field "$before" heartbeat_age_s)
case "$lock" in holding|coasting) [ "$age" != "nil" ] && [ "$age" -lt 30 ] || { log "the lock is $lock but its heartbeat is $age s old: it would not be picked up. Not flashing."; exit 1; };; esac

t_up=$(date +%s); log "upload starts ($(ls -l "$FW" | awk '{print $5}') bytes)"
ssh -s $KEY nerves@$BOXIP fwup < "$FW" 2>&1 | tr '\r' '\n' | grep -E "Success|rror|fail" | tail -1
down=$(date +%s); log "upload done in $((down - t_up)) s: the box is rebooting (DOWN from here)"
sleep 12
while :; do
  [ "$(timeout 8 "$HERE/box" 'IO.puts("UP")' 2>/dev/null | tr -d '\r' | grep -c UP)" = "1" ] && break
  [ $(( $(date +%s) - down )) -gt 300 ] && { log "the box did not come back in 5 min"; echo "{\"at\":\"$(date -u +%FT%TZ)\",\"why\":\"$WHY\",\"came_back\":false}" >> "$HOME/.observatory/outages.jsonl"; exit 1; }
  sleep 2
done
answers=$(( $(date +%s) - down ))
after=$(timeout 30 "$HERE/box" - < "$HERE/before.exs" 2>/dev/null | tr -d '\r' | grep -o 'B .*' | cut -c3-)
log "+$answers s  the box answers; firmware $(field "$after" fw) (was $(field "$before" fw))"

last=""; clock=""; resumed=""; back=""; pictures=""; end=$(( $(date +%s) + 300 )); settled=0
while [ $(date +%s) -lt $end ]; do
  line=$(timeout 12 "$HERE/box" - < "$HERE/poll.exs" 2>/dev/null | tr -d '\r' | grep -o 'P .*' | cut -c3-)
  now=$(( $(date +%s) - down ))
  if [ -n "$line" ] && [ "$line" != "$last" ]; then log "+$now s  $line"; last="$line"; fi
  case "$line" in *"clock true"*) [ -z "$clock" ] && clock=$now;; esac
  case "$line" in *"last {"*) [ -z "$pictures" ] && pictures=$now;; esac
  case "$line" in "lock holding"*) [ -z "$resumed" ] && resumed=$now;; esac
  case "$line" in "lock holding err {"*) [ -z "$back" ] && back=$now; settled=$((settled + 1)); [ $settled -ge 4 ] && break;; esac
  case "$line" in "lock off"*) [ "$lock" = "holding" ] && [ $now -gt 40 ] && case "$line" in *"not running"*|*"not started"*) ;; *) log "the lock did not come back"; break;; esac;; esac
  [ "$lock" != "holding" ] && [ "$lock" != "coasting" ] && [ -n "$pictures$clock" ] && [ $now -gt 60 ] && break
  sleep 3
done
log "summary: answers +${answers} s, clock +${clock:-?} s, pictures +${pictures:-?} s, lock holding +${resumed:-n/a} s, target seen +${back:-n/a} s"
echo "{\"at\":\"$(date -u +%FT%TZ)\",\"why\":\"$WHY\",\"firmware\":\"$(field "$after" fw)\",\"was\":\"$(field "$before" fw)\",\"lock_before\":\"$lock\",\"upload_s\":$((down - t_up)),\"answers_s\":$answers,\"clock_s\":${clock:-null},\"pictures_s\":${pictures:-null},\"holding_s\":${resumed:-null},\"target_seen_s\":${back:-null},\"came_back\":true}" >> "$HOME/.observatory/outages.jsonl"
