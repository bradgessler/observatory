#!/bin/sh
# Look at the built site without a browser window: headless Chrome draws each page to a PNG.
#   preview.sh <out folder> [night]        after `mix site.build`; night defaults to the newest folder in _site/observations
# Writes, for the night's page and every picture's page: desktop (1440 wide), phone (390 wide, in a frame so the
# page lays out as a phone does; a bare 390 px window is clamped to 500 by Chrome), and the share card (1200 x 630,
# the page's <template id="ogplus"> as OpenGraph+ would photograph it: in a body of no set height, so a card
# that leans on height:100% shows here as broken, as it would there).
# Never open these pages in the app's browser pane: it asks the user for permission per site and blocks the session.
set -e
cd "$(dirname "$0")/../../../.."; OUT=$1; SITE=$PWD/_site/observations; NIGHT=${2:-$(ls "$SITE" | grep -v index.html | sort | tail -1)}
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; mkdir -p "$OUT"; P=$SITE/$NIGHT
shot() { "$CH" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=$3,$4 --screenshot="$2" --virtual-time-budget=4000 "file://$1" >/dev/null 2>&1; }
for page in "$P"/*.html; do
  n=$(basename "$page" .html); case $n in _*) continue ;; esac
  shot "$page" "$OUT/$n-desktop.png" 1440 3600
  printf '<!doctype html><body style="margin:0;background:#333"><iframe src="%s.html" style="width:390px;height:4200px;border:0;display:block"></iframe>' "$n" > "$P/_phone.html"
  shot "$P/_phone.html" "$OUT/$n-phone.png" 600 4200
  python3 - "$page" "$P/_card.html" <<'PY'
import re, sys
card = re.search(r'<template id="ogplus">(.*?)</template>', open(sys.argv[1]).read(), re.S).group(1)
open(sys.argv[2], "w").write('<!doctype html><html data-ogplus><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#000">' + card + "</body></html>")
PY
  shot "$P/_card.html" "$OUT/$n-card.png" 1200 630
done
rm -f "$P/_phone.html" "$P/_card.html"; ls "$OUT" | wc -l
