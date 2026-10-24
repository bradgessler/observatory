"""Step 9: coverage, the picture's rectangle, plate solve of the stack, star colours (Gaia DR3), the linear TIF and the
16-bit stretch for step 10.

Coverage: frames per canvas pixel (step 7's outlines). Reported: the area every used frame covers, the area at least
half of them cover ('most'), each as the largest upright rectangle inside it (arcmin). The picture is the largest
upright rectangle where at least COVER_MIN_FRAC of the frames have data (Brad likes the dithering widening the field),
checked for clean edges (the coverage along each edge is reported); M42_COVER_MIN_FRAC=1 gives the all-frames area.

Plate solve (astrometry.net) of the rectangle's green (the joined stack of step 8b); the Trapezium's and M43's catalogue
places on it. Star colours: star_colour.py against Gaia DR3 on the linear stack (the Trapezium's circle left out); the factors go on top of the camera's daylight
balance (M42_COLOUR_CAL=0 leaves the daylight balance). Then render.py: camera matrix, luminance from the four planes,
colour where the light carries it, arcsinh stretch, 16 bits; the pixels where even the short frames came near the
ceiling (step 8b, work/white.npy) shown white."""
import json, os
import numpy as np, cv2, rawpy, tifffile
from common import *
import solvelib, render

COVER_MIN_FRAC = float(os.environ.get('M42_COVER_MIN_FRAC', '0.5'))
TIF_PEDESTAL = 1000.0


def largest_rect(mask, g=4):
    """Largest upright rectangle of True in mask (on a g-px grid; histogram method). Returns x, y, w, h in px."""
    m = mask[::g, ::g]; hh, ww = m.shape; hgt = np.zeros(ww, int); best = (0, 0, 0, 0, 0)
    for y in range(hh):
        hgt = np.where(m[y], hgt + 1, 0); st = []
        for x in range(ww + 1):
            cur = hgt[x] if x < ww else 0; start = x
            while st and st[-1][1] >= cur:
                start, hv = st.pop(); a = hv * (x - start)
                if a > best[0]: best = (a, start, y - hv + 1, x - start, hv)
            st.append((start, cur))
    _, x, y, w, h = best
    return int(x * g + g), int(y * g + g), int(w * g - 2 * g), int(h * g - 2 * g)


if __name__ == '__main__':
    st = np.load(W('stack_mean.npy')); cover = np.load(W('stack_cover.npy')); s8 = jload('step8_stack.json'); N = len(s8['frames'])
    sc = 0.7762 / 60
    cov = {}
    for name, fr in (('all', 1.0), ('most (at least half)', 0.5), ('picture (at least %.0f%%)' % (100 * COVER_MIN_FRAC), COVER_MIN_FRAC)):
        m = (cover >= fr * N) & np.isfinite(st).all(0)
        x, y, w, h = largest_rect(m)
        cov[name] = dict(min_frames=int(np.ceil(fr * N)), area_arcmin2=float(m.sum() * sc * sc), rect_px=[x, y, w, h], rect_arcmin=[round(w * sc, 1), round(h * sc, 1)])
        print('coverage %-28s %.0f arcmin^2; largest upright rectangle %d x %d px = %.1f x %.1f arcmin at (%d, %d)' % (name, cov[name]['area_arcmin2'], w, h, w * sc, h * sc, x, y), flush=True)
    x0, y0, w, h = cov['picture (at least %.0f%%)' % (100 * COVER_MIN_FRAC)]['rect_px']; x1, y1 = x0 + w, y0 + h
    edges = {k: dict(min_frames=int(v.min()), median_frames=int(np.median(v)), min_fraction=round(float(v.min()) / N, 3)) for k, v in dict(top=cover[y0, x0:x1], bottom=cover[y1 - 1, x0:x1], left=cover[y0:y1, x0], right=cover[y0:y1, x1 - 1]).items()}
    inner = cover[y0:y1, x0:x1]
    print('picture rectangle: edges', edges, '; inside it %.1f%% of pixels have every frame, %.1f%% at least 3/4' % (100 * (inner == N).mean(), 100 * (inner >= 0.75 * N).mean()), flush=True)
    stc = st[:, y0:y1, x0:x1]
    G = 0.5 * (stc[1] + stc[2])
    sol = solvelib.solve(G, 'stack')
    cx, cy = solvelib.rd2xy('stack', TARGET['ra_deg'], TARGET['dec_deg'])
    Gs = cv2.GaussianBlur(G, (0, 0), 3.0); xi, yi = int(round(cx)), int(round(cy)); win = Gs[yi - 12:yi + 13, xi - 12:xi + 13]
    yy, xx = np.unravel_index(np.argmax(win), win.shape)
    import step6_solve_ref as S6
    m43 = solvelib.rd2xy('stack', S6.M43['ra_deg'], S6.M43['dec_deg'])
    sol.update(crop_on_canvas=dict(x0=x0, y0=y0, x1=x1, y1=y1, width=w, height=h), coverage=cov, picture_edges=edges, frames=N,
               fraction_inside_with_every_frame=float((inner == N).mean()), fraction_inside_with_three_quarters=float((inner >= 0.75 * N).mean()),
               catalogue=dict(Trapezium=dict(what='theta1 Orionis C', pixel=[float(cx), float(cy)], peak_within_12px=[float(xi - 12 + xx), float(yi - 12 + yy)], offset_arcsec=float(np.hypot(xi - 12 + xx - cx, yi - 12 + yy - cy) * sol['pixscale_arcsec'])),
                              M43_star=dict(what='NU Orionis (HD 37061)', pixel=[float(m43[0]), float(m43[1])])))
    print('stack solved: %.4f arcsec/px, field %.1f x %.1f arcmin, north %.1f deg clockwise from up; theta1 Ori C at (%.0f, %.0f), the peak %.1f arcsec from it; M43\'s star at (%.0f, %.0f)' % (sol['pixscale_arcsec'], *sol['field_arcmin'], sol['north_angle_from_up_deg_clockwise'], cx, cy, sol['catalogue']['Trapezium']['offset_arcsec'], *m43), flush=True)
    jdump(sol, 'step9_solve.json')
    ref = [f for f in jload('step1.json')['frames'] if f['stamp'] == REF_STAMP][0]
    with rawpy.imread(ref['path']) as r: rgb_xyz = np.array(r.rgb_xyz_matrix).tolist()
    RGB_CAM, pre_mul = render.camera_matrix(rgb_xyz)
    wbd = np.array(ref['wb_daylight'][:3]); wb = wbd / wbd[1]; wb_daylight = wb.copy()
    colour = None
    try:
        import star_colour
        from wcs_tan import TanSip
        img = np.dstack([stc[0] * wb[0], 0.5 * (stc[1] + stc[2]), stc[3] * wb[2]]).astype(np.float32)
        wcs = TanSip(os.path.join(WORK, 'solve', 'stack.wcs'))
        hh, ww = img.shape[:2]; yy, xx = np.mgrid[0:hh, 0:ww]
        mask = np.hypot(xx - cx, yy - cy) < OBJ_R_ARCMIN * 60 / sol['pixscale_arcsec']   # the Trapezium's circle: the bright core, stars on bright structured nebula
        ra0, dec0 = wcs.pix2world(ww / 2, hh / 2)
        raw_sky = np.median(np.array(list(s8['constants'].values())), 0)
        colour = star_colour.calibrate(img, wcs, rgb_xyz, wb.tolist(), (float(ra0), float(dec0)), float(0.5 * np.hypot(*sol['field_arcmin']) / 60 + 0.02), mask, 2026 + 290.2 / 365.25,
                                       sensor_xy=None, raw_sky_dn=[float(raw_sky[0]), float(0.5 * (raw_sky[1] + raw_sky[2])), float(raw_sky[3])])
        print(star_colour.summary(colour), flush=True)
        jdump(colour, 'step9b_colour.json')
    except BaseException as e:
        print('star colours NOT calibrated (%r): the daylight balance is used' % (e,), flush=True)
        colour = None
    if COLOUR_CAL and colour:
        wb = wb * np.array([colour['factors']['R'], 1.0, colour['factors']['B']])
    faint = np.load(W('faint_region.npy'))[y0:y1, x0:x1]
    noise = [clipped_stats(stc[p][faint])[1] for p in range(4)]
    assert np.isfinite(stc).all()
    cam = np.dstack([stc[0] * wb[0], 0.5 * (stc[1] + stc[2]), stc[3] * wb[2]])
    t16 = np.clip(np.round(cam + TIF_PEDESTAL), 0, 65535).astype(np.uint16)
    np.save(W('stack_linear_rgb.npy'), cam)      # the linear stack itself (float64 as made, no pedestal, unclipped): the stack FITS (float32) is written from it
    os.makedirs(OUT, exist_ok=True)
    tifffile.imwrite(os.path.join(OUT, 'm42-stack.tif'), t16, photometric='rgb', compression='zlib', metadata=None)
    flat1 = np.ones(stc.shape[1:], np.float32)        # the ceiling test: the frames were divided by a flat within 0.8..1.0 of 1 here
    white = np.load(W('white.npy'))[y0:y1, x0:x1]
    rgb, info, L = render.stretched(stc, flat1, wb, RGB_CAM, noise, ceil=white)
    cv2.imwrite(W('m42-stretched.png'), (rgb[..., ::-1] * 65535 + 0.5).astype(np.uint16))
    for name in ('odd', 'even'):
        if not os.path.exists(W('stack_%s.npy' % name)): continue
        a = np.load(W('stack_%s.npy' % name))[:, y0:y1, x0:x1]
        r2, _, _ = render.stretched(np.nan_to_num(a), flat1, wb, RGB_CAM, noise, ceil=white)
        cv2.imwrite(W('%s-stretched.png' % name), (r2[..., ::-1] * 65535 + 0.5).astype(np.uint16))
    # star size: half-flux diameter of compact unsaturated isolated stars, green, in the stack and the reference frame
    from step2_stars import measure, smooth_light
    sg = np.load(W('stack_single.npy'))[:, y0:y1, x0:x1]
    def hfds(img):
        D = np.nan_to_num(img) - smooth_light(np.nan_to_num(img)); out = []
        sm = cv2.GaussianBlur(D, (0, 0), 2.0); thr = np.percentile(sm, 99.7)
        n, lab, stt, cen = cv2.connectedComponentsWithStats((sm > thr).astype(np.uint8))
        for i in range(1, n):
            r = measure(D, float(cen[i][0]), float(cen[i][1]))
            if r and r['hfr'] and 3000 < r['flux'] and r['peak'] < 9000 and r['elong'] < 1.4: out.append(4 * r['hfr'])
        return out
    hs = hfds(0.5 * (stc[1] + stc[2])); h1 = hfds(0.5 * (sg[1] + sg[2]))
    star = dict(stack_arcsec=float(np.median(hs) * 0.776 / 2), stack_stars=len(hs), reference_frame_arcsec=float(np.median(h1) * 0.776 / 2) if h1 else None)
    print('star size (HFD, green): stack %.2f arcsec (%d stars), reference frame alone %s' % (star['stack_arcsec'], len(hs), star['reference_frame_arcsec']), flush=True)
    jdump(dict(tif=dict(path=os.path.join(OUT, 'm42-stack.tif'), size_px=[int(w), int(h)], pedestal=TIF_PEDESTAL, white_balance=wb.tolist(), origin_on_canvas=[x0, y0]),
               white_balance_daylight=wb_daylight.tolist(), white_balance_applied=wb.tolist(), star_colour_factors=(colour or {}).get('factors'), render_params=render.PARAMS, render_info=info,
               noise_faint_region_dn=dict(zip(PLANE_NAMES, noise)), star_size=star), 'step9_deliver.json')
