"""Step 10: the finished picture, from the north-up stack (step 6 north). In order, each a global formula:
  1. colour: G = mean of G1 and G2; R and B times the camera's as-shot white balance (median over the used frames)
  2. sky: the vignetting dome of step 8 subtracted, then one constant per colour (3-sigma clipped mean of the sky
     outside 3.4 arcmin of M76, stars masked), so dark sky is 0 in R, G and B: neutral before any stretch
  3. crop: CROP_W x CROP_H px round M76's catalogue position (plate solution, step 7), pixels untouched
  4. stretch: render.lum_chroma_stretch: brightness Y = (R + G + B) / 3 through an arcsinh, colour ratios from a copy
     blurred by CHROMA_SIGMA px and faded to grey where that copy's brightness is within a few sigma of the sky
     (the red and blue planes are 2 to 3 times noisier than green, so a pixel's own colour there is noise); sRGB
     curve; 16 bit
  5. finish16.py (finish-pictures' finish.py reading 16 bits): sky to neutral, levels, midtones, quiet sky,
     saturation, with the options in FINISH below
  6. skycheck.py on the result; m76.jpg written by Pillow with no EXIF, GPS or XMP (quality 92, 4:4:4)
Nothing is enlarged: one output pixel is one 2 x 2 colour cell, 0.776 arcsec."""
import json, os, subprocess, sys
import numpy as np, cv2
from PIL import Image
from common import *
from render import lum_chroma_stretch

CROP_W, CROP_H = 640, 480
# chosen by eye from rendered variants (the comparison is in the report): a quiet, neutral sky first, then the nebula's
# bar and lobes; black point at the 64th percentile of brightness, so about a third of the picture is black
STRETCH = dict(white=500.0, soft=40.0, pedestal=3.0, chroma_sigma=3.0, grey_lo=2.0, grey_hi=6.0)
FINISH = ['--neutral', '--neutral-band', '0', '40', '--grey-below', '8', '20', '--black-pct', '64', '--black', '0.025', '--white-pct', '99.97',
          '--gamma', '0.9', '--curve', '0.25', '--sat', '1.1', '--shadow-l', '14', '30', '--median', '5', '--quiet', '6', '16', '75', '--chroma-blur', '6']
PY = sys.executable

g7 = json.load(open(W('step7_grid.json'))); s6 = json.load(open(W('step6_north.json'))); s2 = json.load(open(W('step2.json')))
f2 = {f['stamp']: f for f in s2['frames']}
wb = np.median(np.array([f2[s]['wb'] for s in s6['used']]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
st = np.load(W('north_stack.npy')); dome = np.load(W('north_sky.npy'))
S = np.dstack([st[0] * wb_r, (st[1] + st[2]) / 2, st[3] * wb_b]) - dome.transpose(1, 2, 0)
hh, ww = S.shape[:2]; cx, cy = g7['centre_out_px']
yy, xx = np.mgrid[0:hh, 0:ww]; rr = np.hypot(xx - cx, yy - cy)
G = S[:, :, 1]
sm = cv2.GaussianBlur(G, (0, 0), 2.0); m0, s0, _ = clipped_stats(sm[rr > 260])
bgL = cv2.resize(cv2.medianBlur(cv2.resize(G, (ww // 10, hh // 10), interpolation=cv2.INTER_AREA), 5), (ww, hh))
star = cv2.dilate(((sm - bgL) > 3.5 * s0).astype(np.uint8), np.ones((13, 13), np.uint8)).astype(bool)
SKY = (rr > 260) & ~star
const = [clipped_stats(S[:, :, k][SKY])[0] for k in range(3)]
S = S - np.array(const, np.float32)
x0 = int(round(cx - CROP_W / 2 + 0.5)); y0 = int(round(cy - CROP_H / 2 + 0.5))
C = np.ascontiguousarray(S[y0:y0 + CROP_H, x0:x0 + CROP_W])
# sky noise of the blurred brightness, measured on the sky of the whole grid (for the fade to grey)
Ys = cv2.GaussianBlur(S.astype(np.float32), (0, 0), STRETCH['chroma_sigma']).mean(axis=2)
sky_sigma_cs = clipped_stats(Ys[SKY])[1]


if __name__ == '__main__':
    img16 = lum_chroma_stretch(C, sky_sigma_cs=sky_sigma_cs, bits=16, **STRETCH)
    pre = W('m76-stretched.png')
    cv2.imwrite(pre, img16[:, :, ::-1])
    stem = W('m76-finished')
    r = subprocess.run([PY, os.path.join(SCR, 'finish16.py'), pre, stem] + FINISH, capture_output=True, text=True, check=True); print(r.stdout.strip())
    sc = subprocess.run([PY, os.path.join(SCR, 'skycheck.py'), stem + '.png'], capture_output=True, text=True, check=True).stdout.strip(); print(sc)
    fin = json.load(open(stem + '.json'))
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(stem + '.png').convert('RGB')
    clean = Image.fromarray(np.asarray(im).copy(), 'RGB')                           # a fresh image: no metadata carried over
    clean.save(os.path.join(OUT, 'm76.jpg'), quality=92, subsampling=0, optimize=True)
    # the single reference frame through exactly the same steps, for comparison (kept in the work folder)
    sg = np.load(W('north_single.npy'))
    S1 = np.dstack([sg[0] * wb_r, (sg[1] + sg[2]) / 2, sg[3] * wb_b]) - dome.transpose(1, 2, 0)
    const1 = [clipped_stats(S1[:, :, k][SKY])[0] for k in range(3)]
    C1 = np.ascontiguousarray((S1 - np.array(const1, np.float32))[y0:y0 + CROP_H, x0:x0 + CROP_W])
    Ys1 = cv2.GaussianBlur((S1 - np.array(const1, np.float32)).astype(np.float32), (0, 0), STRETCH['chroma_sigma']).mean(axis=2)
    cv2.imwrite(W('m76-single-stretched.png'), lum_chroma_stretch(C1, sky_sigma_cs=clipped_stats(Ys1[SKY])[1], bits=16, **STRETCH)[:, :, ::-1])
    subprocess.run([PY, os.path.join(SCR, 'finish16.py'), W('m76-single-stretched.png'), W('m76-single-finished')] + FINISH, capture_output=True, text=True, check=True)
    json.dump(dict(white_balance=dict(R=wb_r, G=1.0, B=wb_b, as_shot_raw_median=[float(v) for v in wb]), sky_constant_after_dome_dn=dict(zip('RGB', const)), sky_constant_single_dn=dict(zip('RGB', const1)),
                   sky_region='north-up grid outside 260 px (3.4 arcmin) of the catalogue position, stars masked (3.5 sigma, grown 6 px)',
                   crop=dict(x0=x0, y0=y0, width=CROP_W, height=CROP_H, of_grid=g7['size'], target_px_in_picture=[cx - x0, cy - y0], arcmin=[CROP_W * g7['pixscale_arcsec'] / 60, CROP_H * g7['pixscale_arcsec'] / 60]),
                   stretch=dict(STRETCH, sky_sigma_of_blurred_brightness_dn=sky_sigma_cs, formula=lum_chroma_stretch.__doc__),
                   finish_options=FINISH, finish_recipe=fin, skycheck=sc, linear_max_in_crop=[float(v) for v in C.max((0, 1))]), open(W('step10_finish.json'), 'w'), indent=1)
