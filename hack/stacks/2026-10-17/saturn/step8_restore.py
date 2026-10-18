"""Step 8: divide Titan's blur back out (Richardson-Lucy on brightness, R+G+B; each colour scaled by the same ratio, as
finish2.py of 3 October), and decide how many rounds from a model planet, not by eye: a Saturn of known shape (Horizons'
19.6 arcsec equator, flattening 0.902, rings open 8.6 deg, at the stack's own centre and ring line; globe limb-darkened,
rings B, A, C at fixed fractions of the globe, the Cassini division in it) is blurred by exactly the measured blur, given
the stack's own grain (from the difference of the two half stacks), and put through the same rounds. On the true model the
globe never brightens outward toward the limb; the rounds stop before the model's false rim passes RIM (2 percent of the
globe) in any of 4 noise seeds. A check, not a picture: no pixel of the model goes into any output.
Then the same rounds on the two half stacks: what the halves share is the planet; the Cassini division is called seen
only if both halves show a dip between ring B and ring A at its place (1.95 to 2.02 equatorial radii) on both sides.
Writes work/restored.npy and work/restore.json."""
import cv2
from common import *
from metrics import measure, sample
RIM = float(os.environ.get('SAT_RIM', '0.02')); MAXR = int(os.environ.get('SAT_MAXROUNDS', '40'))
FINE = SCALE / 3

def kernel(s1, s2, th_deg):
    r = int(np.ceil(4 * max(s1, s2))); y, x = np.mgrid[-r:r + 1, -r:r + 1]; t = np.radians(th_deg)
    u = x * np.cos(t) + y * np.sin(t); v = -x * np.sin(t) + y * np.cos(t); k = np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)); return (k / k.sum()).astype(np.float32)

def rl(L, K, n, est=None):
    b = lambda a: cv2.filter2D(a, -1, K, borderType=cv2.BORDER_REFLECT_101); Kf = K[::-1, ::-1].copy(); bt = lambda a: cv2.filter2D(a, -1, Kf, borderType=cv2.BORDER_REFLECT_101)
    L = np.maximum(L, 1e-7).astype(np.float32); est = L.copy() if est is None else est
    for _ in range(n): est = est * bt(L / np.maximum(b(est), 1e-7))
    return est

def model(shape, cx, cy, ang_deg, Re_px, B_deg):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32); a = np.radians(ang_deg)
    u = (xx - cx) * np.cos(a) + (yy - cy) * np.sin(a); v = -(xx - cx) * np.sin(a) + (yy - cy) * np.cos(a); sB = abs(np.sin(np.radians(B_deg)))
    Rp = Re_px * np.sqrt((0.902 ** 2) * (1 - sB ** 2) + sB ** 2); rho = np.hypot(u / Re_px, v / Rp)
    globe = np.where(rho < 1, 0.35 + 0.65 * np.sqrt(np.clip(1 - rho ** 2, 0, 1)), 0)
    rr = np.hypot(u, v / sB) / Re_px; ring = np.select([(rr > 1.24) & (rr < 1.53), (rr >= 1.53) & (rr < 1.95), (rr >= 2.02) & (rr < 2.27)], [0.12, 0.75, 0.45], 0)
    behind = (rho < 1) & (v * np.sign(B_deg) > 0)            # the far half of the rings is hidden by the globe
    return np.where(behind, globe, np.maximum(globe, ring) if False else globe + ring * (rho >= 1) + ring * (rho < 1) * 0.6).astype(np.float32), rho

def rim(img, rho, wedge):
    edges = np.arange(0.40, 0.96, 0.05); p = [float(img[(rho >= e) & (rho < e + 0.05) & wedge].mean()) for e in edges]
    return max(max(max(p[i + 1:]) - p[i] for i in range(len(p) - 1)), 0.0) / p[0]

if __name__ == '__main__':
    S = np.load(W('stack.npy')); H0 = np.load(W('half0.npy')); H1 = np.load(W('half1.npy')); ti = jload('titan.json'); eph = jload('ephemeris.json')
    s1, s2 = ti['sigma_fine_px']; K = kernel(s1, s2, ti['long_axis_deg_in_picture'])
    m, _ = measure(S[:, :, 1]); cx, cy = m['centre']; ang = m['ring_line_deg']; Re = eph['equatorial_diameter_arcsec'][2] / 2 / FINE; B = eph['ring_opening_deg'][2]
    L = S.sum(2); globe = float(np.median(L[int(cy) - 10:int(cy) + 10, int(cx) - 10:int(cx) + 10]))
    grain = float((H0.sum(2) - H1.sum(2))[int(cy) - 40:int(cy) + 40, int(cx) - 40:int(cx) + 40].std() / 2 / globe)   # per fine px, for the full stack: (A - B) / 2
    truth, rho = model(L.shape, cx, cy, ang, Re, B); yy, xx = np.indices(L.shape); a = np.radians(ang)
    vv = -(xx - cx) * np.sin(a) + (yy - cy) * np.cos(a); uu = (xx - cx) * np.cos(a) + (yy - cy) * np.sin(a); wedge = np.abs(vv) > np.abs(uu)      # within 45 deg of the poles, away from the rings
    seen = cv2.filter2D(truth, -1, K, borderType=cv2.BORDER_REFLECT_101); rounds = list(range(0, MAXR + 1, 2)); res = {r: [] for r in rounds}
    for seed in range(5):
        rng = np.random.default_rng(seed); nz = cv2.GaussianBlur(rng.normal(0, 1, seen.shape).astype(np.float32), (0, 0), 1.5); nz *= grain / nz.std()
        obs = np.maximum(seen + (nz * np.sqrt(np.clip(seen, 0.02, None)) if seed else 0), 1e-7); est = obs.copy(); done = 0
        for r in rounds:
            est = rl(obs, K, r - done, est); done = r; res[r].append(rim(est, rho, wedge))
    ok = [r for r in rounds if max(res[r]) < RIM]; chosen = int(os.environ.get('SAT_ROUNDS', max([r for r in rounds if all(q in ok for q in rounds if q <= r)])))
    for r in rounds: print('%2d rounds: false rim on the model %.4f without noise, up to %.4f with the stack\'s grain' % (r, res[r][0], max(res[r][1:])))
    print('grain %.4f of the globe per fine px; blur %.2f x %.2f arcsec; rounds chosen: %d (rim under %.2f)' % (grain, *ti['fwhm_arcsec'], chosen, RIM))
    def restore(X):
        Lx = X.sum(2); E = rl(Lx, K, chosen); return X * (E / np.maximum(Lx, 1e-7))[:, :, None]
    R = restore(S); R0 = restore(H0); R1 = restore(H1); np.save(W('restored.npy'), R.astype(np.float32))
    # the Cassini division: a dip between B and A on both sides, in both restored halves
    def cassini(X):
        g = X[:, :, 1]; r = np.arange(-int(2.4 * Re), int(2.4 * Re) + 1, 1.0); p = sample(g, cx, cy, np.radians(ang), r, half=2); out = {}
        for side, nm in ((-1, 'one end'), (1, 'other end')):
            q = lambda k: float(np.interp(side * k * Re, r, p) if side > 0 else np.interp(-k * Re, r, p))
            out[nm] = dict(ring_B_1p8=q(1.80), division_1p985=q(1.985), ring_A_2p15=q(2.15), dip=round(min(q(1.80), q(2.15)) - q(1.985), 6) / max(q(1.80), 1e-9))
        return out
    cas = dict(plain=cassini(S), restored=cassini(R), half0=cassini(R0), half1=cassini(R1))
    seen_ = all(cas[k][s]['dip'] > 0 for k in ('half0', 'half1') for s in ('one end', 'other end'))
    mR, _ = measure(R[:, :, 1])
    jsave('restore.json', dict(method='Richardson-Lucy on R+G+B, each colour scaled by the same ratio', psf='elliptical Gaussian from Titan (step 7)', psf_fwhm_arcsec=ti['fwhm_arcsec'], psf_long_axis_deg=ti['long_axis_deg_in_picture'],
                               rounds=chosen, rim_limit=RIM, model_rim_by_rounds={str(r): dict(no_noise=round(res[r][0], 5), with_grain_max=round(max(res[r][1:]), 5)) for r in rounds}, grain_of_globe=grain,
                               model=dict(equatorial_radius_arcsec=Re * FINE, flattening=0.902, ring_open_deg=B, ring_line_deg=ang, ring_radii_Re=dict(C=[1.24, 1.53], B=[1.53, 1.95], cassini=[1.95, 2.02], A=[2.02, 2.27]), ring_level=dict(C=0.12, B=0.75, A=0.45)),
                               cassini=cas, cassini_seen=seen_, metrics_plain=m, metrics_restored=mR))
    print('Cassini division (ring level at 1.985 Re below both B at 1.8 and A at 2.15, as a fraction of B):')
    for k, v in cas.items(): print('  %-9s' % k, {s: round(x['dip'], 4) for s, x in v.items()})
    print('seen in both halves on both sides:', seen_)
    print('restored: polar limb %.3f", ansa %.3f", gap contrast %.4f (plain %.3f", %.3f", %.4f)' % (mR['polar_limb_10_90_arcsec'], mR['ansa_width_fwhm_arcsec'], mR['gap_contrast'], m['polar_limb_10_90_arcsec'], m['ansa_width_fwhm_arcsec'], m['gap_contrast']))
