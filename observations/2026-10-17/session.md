---
title: "Night of 17 October 2026"
date: 2026-10-17
summary: "Four targets and as long as the night allows on each: the Dumbbell Nebula, the Triangulum Galaxy, Saturn, and the Orion Nebula."
Location: San Francisco Bay Area. A driveway at home, with trees on most sides
Telescope: Celestron 8SE Schmidt-Cassegrain. 203 mm aperture, about 2,085 mm focal length by plate solve, f/10.3
Camera: Sony a6000, stock, at prime focus. APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW
Field: 38.8 x 25.9 arcmin in one frame, 0.388 arcsec per pixel
Mount: Sky-Watcher EQ6-R, set down without polar alignment. Aligned from plate-solved photos and driven from that model, unguided
Computer: Raspberry Pi 3 running Observatory, in Elixir
Sky: Clear and still. A Moon a little under half lit, low in the southwest early on and soon behind the garage
Processing: Stacked from the RAW frames with numpy, OpenCV and rawpy. No darks tonight: hot pixels found from each run itself. Flats from open sky and earlier twilight frames, with tonight's dust measured on each run's own sky and divided out. Star colours from the Gaia catalogue. Plate solving by astrometry.net. Nothing generated
---

Last week the telescope worked through eleven targets in a night and got a few minutes of light on each. Tonight it goes the other way: a few targets, hours on each, and a camera that starts its next picture while the last one is still being saved.

The night started late. The focus was off, which nothing in software can fix, so the first hour went to setting the telescope up on Vega and reading star sizes off each picture while I turned the focus knob, from 12 arcseconds down to 5. Then the Triangulum Galaxy was still behind a tree, so the telescope went to the Dumbbell Nebula, high overhead, until the galaxy climbed clear.

This page fills in as the night goes. The problems we ran into along the way are written up as technical notes.
