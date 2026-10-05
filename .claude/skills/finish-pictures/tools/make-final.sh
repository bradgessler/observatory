#!/bin/sh
# The finished set in final/: tilted mosaics levelled and cropped (level.py), then levels and colour (finish.py).
# Every number here is the recipe; rerun this after any stack is remade. PY must have numpy and OpenCV.
# Sources: M31, M31M and M45 choose between the first stacks (before-flats/) and the twilight-flat rerun (in place).
cd "$(dirname "$0")"; PY=${PY:-python3}; mkdir -p final
# Since the twilight-flat rerun: the Andromeda mosaic is the rerun (two false dust smudges gone); the core stays the cloud-flat
# version (the rerun's chaff shadow is larger); the Pleiades rerun is the same picture to 0.14 DN, so the first one stays.
M31=${M31:-m31/before-flats}; M31M=${M31M:-m31/mosaic}; M45=${M45:-m45/before-flats}
$PY level.py $M31M/m31-mosaic.png m31/mosaic/m31-mosaic-level
$PY level.py $M45/m45-mosaic.png m45/m45-mosaic-level --coverage $M45/m45-mosaic-coverage.tif
$PY level.py m42/m42-mosaic.png m42/m42-mosaic-level
$PY level-planet.py saturn/sharp/saturn-sharp-finished.png saturn/sharp/saturn-sharp-level.png 460 260
$PY finish.py m42/m42.png final/orion-nebula --neutral --neutral-band 0 12 --grey-below 3 11 --black-pct 6 --black 0.03 --white-pct 99.97 --gamma 0.95 --curve 0.3 --sat 1.6 --quiet 2.5 10 38 --chroma-blur 4
$PY finish.py m42/m42-mosaic-level.png final/orion-nebula-wide --neutral --neutral-band 0 25 --grey-below 3 11 --black-pct 22 --black 0.025 --white-pct 99.97 --gamma 1.0 --curve 0.3 --sat 1.5 --quiet 3 12 42 --chroma-blur 5
$PY crop.py $M31/m31-core-cloudflat.png m31/m31-core-cropped 0 180 2892 1743 "the top 180 rows hold the shadow of a piece of chaff in the light path, found and blown off the next morning"
$PY finish.py m31/m31-core-cropped.png final/andromeda-core --neutral --neutral-band 4 45 --black-pct 2 --black 0.03 --white-pct 99.99 --gamma 1.2 --curve 0.45 --sat 1.2 --quiet 2.5 14 48 --chroma-blur 5
$PY finish.py m31/mosaic/m31-mosaic-level.png final/andromeda-mosaic --neutral --neutral-band 0 25 --grey-below 3 10 --black-pct 12 --black 0.03 --white-pct 99.99 --gamma 1.2 --curve 0.3 --sat 1.3 --quiet 3.5 14 48 --chroma-blur 6
$PY finish.py m45/m45-mosaic-level.png final/pleiades --neutral --neutral-band 0 40 --grey-below 2 8 --black-pct 45 --black 0.0 --white-pct 99.98 --gamma 0.95 --curve 0.15 --sat 1.45 --median 5 --quiet 5 12 50 --chroma-blur 8
$PY finish.py m15/m15-stack.png final/m15 --black-pct 45 --black 0.025 --white-pct 99.97 --curve 0.2 --sat 1.5 --shadow-l 14 30 --grey-below 6 16 --quiet 2.5 9 30 --chroma-blur 3
$PY finish.py ngc7662/ngc7662-stack-close.png final/blue-snowball --black-pct 75 --black 0.015 --white-pct 99.99 --curve 0.2 --sat 1.4 --shadow-l 20 45 --grey-below 8 25 --quiet 3 10 40 --chroma-blur 5
$PY finish.py moon/moon-last-quarter-restored.png final/moon --neutral --neutral-band 0 45 --grey-below 4 14 --black-pct 0.5 --black 0.0 --white-pct 99.95 --gamma 0.95 --curve 0.35 --sat 1.0
$PY finish.py saturn/sharp/saturn-sharp-level.png final/saturn --neutral --neutral-band 0 40 --grey-below 3 12 --black-pct 2 --black 0.0 --white-pct 99.9 --curve 0.2 --sat 1.5
