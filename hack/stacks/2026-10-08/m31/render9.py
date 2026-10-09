"""The stretch and the finish, shared by step 9 (the stack) and step 10 (its deconvolved copy), so that the two get the
same treatment. Fixed formulas applied to every pixel alike; the only search is for the nucleus's place under white.

Stretch: arcsinh on brightness (green) about the zero level,
    f = (asinh(v / soft) - asinh(-floor / soft)) / (asinh(white / soft) - asinh(-floor / soft)), v clipped to -floor..white
(noise below the zero is kept down to -floor instead of being cut at the zero: cut pixels would be exact black, which
the finish tool reads as 'no data'); colour ratios kept, taken from a copy blurred by chroma_sigma px,
ratio_c = (C_c + cped) / (C_g + cped); out_c = sRGB(ratio_c x f); 16-bit.
White: the first of core_list (the nucleus's place as a fraction of white after the arcsinh) that leaves the nucleus
at 250 of 255 or less after the WHOLE chain (the finish's S-curve and saturation lift it further).
Finish: finish16.py with the given options. JPEGs by Pillow, no metadata; the 1600 px copy is an area average down."""
import os, sys, subprocess
import numpy as np, cv2
from PIL import Image

SCR = os.path.dirname(os.path.abspath(__file__))


def srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def picture(rgb, nuc_xy, gnuc, stem, finish, core_list, soft, floor, cped, chroma_sigma, log=print):
    h, w = rgb.shape[:2]
    L = rgb[:, :, 1].astype(np.float64)
    C = cv2.GaussianBlur(rgb, (0, 0), chroma_sigma)
    den = np.maximum(C[:, :, 1] + cped, 0.25 * cped)
    ratio = np.maximum(C + cped, 0) / den[:, :, None]
    Yc, Xc = np.mgrid[0:h, 0:w]; disc = np.hypot(Xc - nuc_xy[0], Yc - nuc_xy[1]) <= 10

    def curve(v, white):
        a, b = np.arcsinh(-floor / soft), np.arcsinh(white / soft)
        return (np.arcsinh(np.clip(v, -floor, white) / soft) - a) / (b - a)

    def white_for(core_at):
        lo, hi = gnuc * 1.0001, gnuc * 1e4
        for _ in range(200):
            mid = np.sqrt(lo * hi)
            if curve(gnuc, mid) > core_at: lo = mid
            else: hi = mid
        return float(np.sqrt(lo * hi))

    stretched = stem + '-asinh-16bit.png'; tried = []
    for core_at in core_list:
        white = white_for(core_at)
        out = srgb(ratio * curve(L, white)[:, :, None])
        cv2.imwrite(stretched, (out * 65535 + 0.5).astype(np.uint16)[:, :, ::-1])
        r = subprocess.run([sys.executable, os.path.join(SCR, 'finish16.py'), stretched, stem] + finish, capture_output=True, text=True)
        fin16 = cv2.imread(stem + '-16bit.png', cv2.IMREAD_UNCHANGED)[:, :, ::-1]
        fin8 = (fin16.astype(np.float32) / 257.0 + 0.5).astype(np.uint8)
        mx = int(fin8[disc].max()); tried.append(dict(core_at=core_at, white_dn=round(white, 1), nucleus_max_8bit=mx))
        log('stretch: soft %.1f floor %.1f white %.0f DN (nucleus %.0f DN at %.2f of white) -> nucleus max %d of 255 after the finish | %s' % (soft, floor, white, gnuc, core_at, mx, r.stdout.strip()))
        if mx <= 250: break
    core = dict(max_8bit_in_any_channel_within_10px_of_nucleus=int(fin8[disc].max()), pixels_at_255_there=int((fin8[disc] == 255).any(1).sum()), max_16bit_finished_there=int(fin16[disc].max()))
    return fin16, fin8, dict(soft=soft, floor=floor, colour_pedestal=cped, chroma_sigma_px=chroma_sigma, core_at=core_at, white_dn=white, tried=tried), core


def save_jpegs(fin16, dest, name, w1600=1600):
    h, w = fin16.shape[:2]
    fin8 = (fin16.astype(np.float32) / 257.0 + 0.5).astype(np.uint8)
    p1 = os.path.join(dest, name + '.jpg'); p2 = os.path.join(dest, name + '-1600.jpg')
    Image.fromarray(fin8, 'RGB').save(p1, quality=92, subsampling=0, optimize=True)
    s = cv2.resize(fin16.astype(np.float32), (w1600, int(round(h * w1600 / w))), interpolation=cv2.INTER_AREA)
    Image.fromarray((s / 257.0 + 0.5).clip(0, 255).astype(np.uint8), 'RGB').save(p2, quality=90, subsampling=0, optimize=True)
    for p in (p1, p2):
        im = Image.open(p); assert not im.getexif() and 'exif' not in im.info and 'icc_profile' not in im.info, p
    sky = subprocess.run([sys.executable, os.path.join(SCR, 'skycheck.py'), p1, p2], capture_output=True, text=True).stdout
    return p1, p2, sky
