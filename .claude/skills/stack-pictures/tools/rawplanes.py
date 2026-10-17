"""RAW frames as colour planes: the reading shared by the calibration tools (twilight_flat, darks, flatcheck).

What it does: reads a Sony a6000 RAW (ARW) in place with rawpy and splits it into its four colour planes R, G1, G2, B
(black subtracted with the RAW's own black level per channel, no demosaic); reads exposure and ISO from the RAW's own
EXIF (the sidecar can be wrong); robust block means; a star mask; the night's index.jsonl as a list of frames.

Inputs: a RAW path (never written). Outputs: numpy arrays. Recipe entries: none of its own; the callers record
`black_dn`, `exposure_s`, `iso` and the plane order from here.

Conventions (the same as every pipeline under hack/stacks/): plane order R, G1, G2, B; cell offsets (ox, oy) R (0,0),
G1 (1,0), G2 (0,1), B (1,1); plane pixel (X, Y) is sensor pixel (2X + ox, 2Y + oy); a plane is 2012 x 3012 px.

Note on the data: this camera's RAW values are multiples of 4 at ISO 100 and 3200 alike, so a MEDIAN of a block of
sky is quantised (82 DN of sky moves in 5% steps). Large-scale levels here are clipped MEANS, which are not."""
import glob, json, os
import numpy as np

PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]
H, WD = 4024, 6024                    # raw_image_visible
H2, W2 = H // 2, WD // 2              # one colour plane
CENTRE = np.array([3011.5, 2011.5])   # sensor centre, sensor px
CEILING = 15488.0                     # 16000 - 512: the raw ceiling above black, as the pipelines use it


def raw_exif(path):
    """(exposure_s, iso) from the RAW's own EXIF."""
    import tifffile
    with tifffile.TiffFile(path) as t:
        ex = t.pages[0].tags['ExifTag'].value
    e = ex.get('ExposureTime'); e = e[0] / e[1] if isinstance(e, tuple) else float(e)
    return float(e), int(ex.get('ISOSpeedRatings'))


def read_planes(path, black=None):
    """(4, 2012, 3012) float32 planes minus black, and facts. `black` overrides the RAW's black level (4 values, R G1 G2 B)."""
    import rawpy
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat = r.raw_pattern; desc = r.color_desc.decode()
        bl = np.array(r.black_level_per_channel, np.float32)
        meta = dict(black_dn=bl.tolist(), white=float(r.white_level), wb_daylight=[float(v) for v in r.daylight_whitebalance],
                    rgb_xyz_matrix=np.array(r.rgb_xyz_matrix).tolist())
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]] and raw.shape == (H, WD), (desc, pat.tolist(), raw.shape)
    b = [bl[pat[oy, ox]] for ox, oy in OFFS] if black is None else list(black)
    P = np.stack([raw[oy::2, ox::2] - np.float32(b[i]) for i, (ox, oy) in enumerate(OFFS)])
    meta['black_used_dn'] = [float(v) for v in b]
    return P, meta


def clipped_mean(v, k=3.0, iters=5):
    """Mean, std and count of v after k-sigma clipping (NaN ignored)."""
    v = np.asarray(v, np.float64).ravel(); v = v[np.isfinite(v)]
    if v.size == 0: return np.nan, np.nan, 0
    m, s = float(np.median(v)), float(1.4826 * np.median(np.abs(v - np.median(v))) or v.std() or 1.0)
    for _ in range(iters):
        w = v[np.abs(v - m) <= k * s]
        if w.size < 3: break
        m, s = float(w.mean()), float(w.std() or s)
    return m, s, int(w.size)


def block_means(A, bk, mask=None, k=3.0, min_frac=0.25):
    """Clipped block means of a 2-D array on bk x bk blocks (pixels where mask is True left out; NaN left out). One clip
    round about the block median (k x 1.4826 MAD) then the mean. Blocks with less than min_frac of their pixels -> NaN."""
    h, w = A.shape; ny, nx = h // bk, w // bk
    a = A[:ny * bk, :nx * bk].astype(np.float32)
    if mask is not None: a = np.where(mask[:ny * bk, :nx * bk], np.nan, a)
    v = a.reshape(ny, bk, nx, bk).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        med = np.nanmedian(v, axis=2)
        mad = 1.4826 * np.nanmedian(np.abs(v - med[..., None]), axis=2)
        mad = np.maximum(mad, 1.0)                       # the DN quantisation (steps of 4) makes a MAD of 0 possible
        keep = np.abs(v - med[..., None]) <= k * mad[..., None]
        out = np.nansum(np.where(keep, v, 0), axis=2) / keep.sum(2)
    out[keep.sum(2) < min_frac * bk * bk] = np.nan
    return out.astype(np.float32)


def star_mask(G, k=4.0, grow=6, bright_k=40.0, bright_grow=24):
    """Pixels of stars (and anything compact and brighter than the smooth light under it) in a 2-D plane: above the
    smooth level (16 px block medians, 5 x 5 median of those) by k sigma after a 1.5 px Gaussian, grown by `grow` px;
    above bright_k sigma grown by bright_grow px. Returns a bool array."""
    import cv2
    h, w = G.shape; bk = 16; ny, nx = h // bk, w // bk
    b = np.median(G[:ny * bk, :nx * bk].reshape(ny, bk, nx, bk).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2).astype(np.float32)
    sm = cv2.resize(cv2.medianBlur(b, 5), (w, h), interpolation=cv2.INTER_LINEAR)
    D = cv2.GaussianBlur((G - sm).astype(np.float32), (0, 0), 1.5)
    d = D[::3, ::3]; s = 1.4826 * np.median(np.abs(d - np.median(d)))
    el = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m1 = cv2.dilate((D > k * s).astype(np.uint8), el(grow))
    m2 = cv2.dilate((D > bright_k * s).astype(np.uint8), el(bright_grow))
    return (m1 | m2).astype(bool)


def index_rows(night):
    """The night's index.jsonl, one dict per picture, with 'arw' set to the RAW's path when it is on this machine."""
    out = []
    for line in open(os.path.join(night, 'index.jsonl')):
        j = json.loads(line)
        arw = [f['name'] for f in j.get('files', []) if f.get('format') == 'arw']
        p = os.path.join(night, arw[0]) if arw else None
        j['arw'] = p if p and os.path.exists(p) else None
        out.append(j)
    return out


def sensor_xy_of_plane(p, shape=(H2, W2)):
    """Sensor x, y (px) of every pixel of colour plane p."""
    ox, oy = OFFS[p]
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    return 2 * xx + ox, 2 * yy + oy
