---
name: finish-pictures
description: Finish stacked astronomy pictures for showing — turn a tilted mosaic level and crop it, crop a flaw off an edge, set black and white levels, lift midtones, quiet the dark sky, and bring colour out, all with deterministic tools that write a recipe. Use when the user asks to rotate, crop, adjust levels, saturate, denoise or "make it pop", or says a picture is too warm, too noisy, too dark or tilted.
---

# Finish a stack into a picture

A stack is linear-ish and plain. This is the step that makes it a picture
without making anything up. The tools are in `tools/`; copy them into the
night's folder (`~/.observatory/nights/<night>/`) and run them there.

## The user's rules, from the corrections they gave

- "Don't overdo it or fake stuff, just draw out the best in the features
  with deterministic photo algorithms." No generative step, no retouching.
  The stack is never overwritten: finishing writes new files and a JSON
  recipe beside each.
- "The black is dark red and not black. You went too far." **Dark sky is
  neutral.** Measure it, do not judge it: `skycheck.py` prints the mean
  R, G, B of the darkest 10 percent and the next 30. R−G and B−G should be
  within about 1 of 255.
- "I'd rather have less feature and less noise if given the trade off."
  Raise the black point and smooth the dark sky before reaching for faint
  detail.
- "Don't enlarge." Never resample a picture above its own pixels.

## Tools

    level.py <north-up mosaic.png> <out stem> [--coverage map.tif] [--keep-holes N]
        Finds the tilt of the data's edge, turns once (Lanczos), crops to the largest rectangle with no empty
        corner. Writes the turn, the crop and the 2 x 3 map from source pixels to these (annotations need it).
        Use --coverage when true-black sky reads as "no data".
    level-planet.py <in.png> <out.png> [w] [h]
        Turns a planet so its long axis (the rings) lies level.
    crop.py <in.png> <out stem> x y w h "<why>"
        Cuts a rectangle, pixels untouched, and writes down why. For a flaw at an edge: crop it, never paint it.
    finish.py <in.png> <out stem> [options]
        In order: sky to neutral, levels, midtones, quiet sky, saturation. Writes PNG, JPG and the recipe.
    skycheck.py <picture.png> ...
        The dark sky's colour, in numbers.
    make-final.sh
        The night's whole recipe, one line per picture. Every number is in this file; rerun it when a stack changes.

`finish.py` options, in the order they act:

| Option | What it does | Start from |
|---|---|---|
| `--neutral`, `--neutral-band lo hi` | shifts R, G, B so the given percentile band of dark sky is grey | band 0 25; wider (0 40) for a star field, narrower (0 12) when nebula fills the frame |
| `--black-pct`, `--black`, `--white-pct` | black and white points by percentile | black-pct at the sky's level: 2 to 12 where the object fills the frame, 45 to 75 for a small object on empty sky |
| `--gamma`, `--curve` | midtone lift and an S-curve on brightness; colour ratios kept | gamma 0.95 to 1.2, curve 0.15 to 0.45 |
| `--quiet sigma L0 L1`, `--median k`, `--chroma-blur s` | smooths brightness (bilateral, optional median first) and blurs colour, only where the picture is dark (between L0 and L1) | `--quiet 2.5 10 38 --chroma-blur 4`; a short mosaic needs `--median 5 --quiet 5 12 50` |
| `--sat`, `--shadow-l a b`, `--grey-below a b` | CIELAB chroma times a factor, faded out in shadows and highlights; below `a` the sky has no colour at all | 1.2 for a galaxy, 1.4 to 1.6 for a nebula, 1.0 for the Moon |

## How to work

1. Level and crop first, then finish: levels are percentiles of what is in
   the frame.
2. One picture at a time. Run `finish.py`, run `skycheck.py`, **look at the
   result** at full size and as a small preview. Then change one number.
3. When the sky is brown, red or green: `--neutral` with a band that holds
   only sky, and `--grey-below` so noise carries no colour.
4. When it is noisy: black point up, `--quiet` stronger, `--chroma-blur`
   wider. Check that stars and the object's edge have not gone soft: the
   smoothing must stay in the dark.
5. A flaw at an edge (a dust shadow): `crop.py`, with the reason. The
   Andromeda core lost its top 180 rows to a piece of chaff this way.
6. Put the final line in `make-final.sh`. That file is the recipe.

What it looked like on the night of 3 October 2026 is in
`tools/make-final.sh`: nine pictures, nine lines.

## Then

`annotate-pictures` for the versions people share, `publish-observations`
for the website.
