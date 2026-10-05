# Moon mosaic from stills (a probe, kept as a record)

The night of 2026-10-02 the a6000 on the 8SE took 243 pictures of a
third-quarter Moon that never quite fit the frame, through cloud, from a
garage. This turns them into one picture of the whole lit Moon, at the
sensor's own pixel scale, sharper than any single frame, with imaging
arithmetic only: no step predicts or invents a pixel. Python, because it was
a day's experiment; the product path is Elixir driving the same
deterministic steps.

    ./run.sh ~/.observatory/nights/2026-10-02-a6000/moon/box-full ~/.observatory/nights/2026-10-02-a6000/mosaic

## The steps

1. `grade.py`: every frame from its JPEG: is the Moon there, how much, is it
   under cloud. 93 of 243 had no Moon.
2. `moonlib.load`: each RAW as colour planes, one value per 2x2 colour cell
   per colour. No demosaicing, so no colour is interpolated from its
   neighbours.
3. `register.py`: craters matched between frames (SIFT), each frame's
   rotation, shift and scale onto one common Moon solved from the matches
   that agree (RANSAC). About 660 agreeing matches a frame, 1 px fit. The
   rotation it finds is real field rotation (the mount wasn't polar aligned);
   the scale drifts a little because the Moon's distance does.
4. `stack.py ref`: the placed frames averaged into a yardstick: soft, but
   the air's wobble averages out of it.
5. `stack.py local`: per frame, a grid of 48 px patches each matched to the
   yardstick: how far the air moved that patch (0.7 px typical). Then, patch
   in place, how much detail it holds, with the noise (known from the two
   green pixels of each cell) subtracted.
6. `stack2x.py`: per patch, the sharpest 10% of the frames covering it,
   averaged on the sensor's pixel grid: each of a frame's four colour planes
   is read at its own place in the colour cell, once (Lanczos). Clipped
   pixels count for nothing; a frame fades out at its sensor edge.
7. `measure.py`, `psf.py`: on the stack: how far apart the colour planes sit
   (the air is a weak prism), where the limb is, and the blur's spectrum,
   from the sunlit limb. It falls as exp(-(f/f0)^1.75): the air's own
   signature is 5/3.
8. `frc.py`: two stacks from separate halves of the frames, compared scale by
   scale (Fourier ring correlation). What both halves show is real; noise is
   different in each. This is the resolution, with no model: the halves agree
   to 3.1 arcsec strictly, 2.4 by the usual 1/7 criterion.
9. `wiener.py`: the restored picture. At each scale, contrast is multiplied
   by (the share that is signal, from 8) / (the contrast the blur left,
   from 7). At the limb the result is held between the original's own local
   darkest and brightest, because every such filter rings at a hard edge.

## What was tried and measured (`judge.py`, `frameblur.py`, `spectrum.py`)

- A single frame holds detail to about 4.5 arcsec; its limb blur is 2.8
  (the best frame) to 3.9 (the median).
- Keeping fewer frames per patch sharpens the stack and raises its noise:
  limb blur 3.24 arcsec at 5%, 3.29 at 10%, 3.54 at 30%, 3.78 at 50%.
- A sharper yardstick (the stack itself) and smaller patches changed
  nothing: alignment is not what limits it. The frames are.
- A Wiener filter with the noise guessed from the spectrum's tail amplified
  noise 190 times. Half against half is the measurement to trust.
- Richardson-Lucy (`finish.py N`) works, but stalls before the fine scales
  are restored.

## What it writes

`moon-full-resolution.tif/.jpg` (the stack as it is, linear 16-bit),
`moon-full-resolution-restored.tif/.jpg`, `frames.csv` (every frame: used
or discarded, and why) and `recipe.json` (every step and number).
