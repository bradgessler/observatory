"""Step 1: find tonight's 1/60 s ISO 400 frames of Almach. The index gives camera settings, time and pointing; the RAW's own EXIF
is the check on the settings (the sidecar can be wrong when settings changed). Frames at ISO 400, 1/60 s in the time window
that point somewhere else (other targets of the same short-exposure run) are listed and left out."""
import os, json, glob, math
import numpy as np
from common import *


def raw_exif(path):
    import tifffile
    with tifffile.TiffFile(path) as t:
        ex = t.pages[0].tags['ExifTag'].value
    e = ex.get('ExposureTime'); e = e[0] / e[1] if isinstance(e, tuple) else float(e)
    return e, ex.get('ISOSpeedRatings', ex.get('PhotographicSensitivity'))


def sep_deg(ra1, d1, ra2, d2):
    a = math.radians
    c = math.sin(a(d1)) * math.sin(a(d2)) + math.cos(a(d1)) * math.cos(a(d2)) * math.cos(a(ra1 - ra2))
    return math.degrees(math.acos(max(-1, min(1, c))))


if __name__ == '__main__':
    recs = [json.loads(l) for l in open(os.path.join(NIGHT, 'index.jsonl'))]
    found, used, left = [], [], []
    for r in recs:
        arw = [f['name'] for f in r['files'] if f['name'].endswith('.ARW')]
        if not arw: continue
        n = arw[0]
        if not (T0 <= n[:15] <= T1): continue
        if r['camera'].get('iso') != ISO or str(r['camera'].get('shutter')) != SHUTTER: continue
        p = r.get('pointing') or {}
        d = sep_deg(p['ra_deg'], p['dec_deg'], TARGET['ra_deg'], TARGET['dec_deg']) if p.get('ra_deg') is not None else None
        e, iso = raw_exif(os.path.join(NIGHT, n))
        item = dict(file=n, iso_sidecar=r['camera']['iso'], shutter_sidecar=r['camera']['shutter'], exif_exposure_s=e, exif_iso=iso,
                    pointing_ra_deg=p.get('ra_deg'), pointing_dec_deg=p.get('dec_deg'), degrees_from_almach=None if d is None else round(d, 3),
                    shutter_pressed=r['time'].get('shutter_pressed'))
        found.append(item)
        if d is not None and d < POINT_RADIUS_DEG and abs(e - 1 / 60) < 0.002 and iso == ISO: used.append(item)
        else:
            item['why_left_out'] = ('pointing %.1f deg from Almach: another target' % d) if d is not None and d >= POINT_RADIUS_DEG else 'settings in the EXIF do not match'
            left.append(item)
    print('1/60 s ISO 400 frames %s..%s: %d found, %d on Almach, %d on other targets' % (T0, T1, len(found), len(used), len(left)))
    for u in used: print('  use ', u['file'], u['degrees_from_almach'])
    for u in left: print('  skip', u['file'], u['why_left_out'])
    jdump(dict(window=[T0, T1], settings=dict(iso=ISO, shutter=SHUTTER), found=len(found), used=len(used), used_files=[u['file'] for u in used], used_detail=used, left_out=left), 'step1_frames.json')
