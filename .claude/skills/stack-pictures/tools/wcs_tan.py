"""Sky to pixel and back with a plate solution (TAN projection with SIP distortion), without astropy.

What it does: reads the solution astrometry.net wrote (a .wcs file, or the 'wcs_header' dict a recipe.json keeps) and
turns RA, Dec into array pixels (x = column, y = row, 0-based: FITS pixel minus 1) through the inverse SIP terms
(AP, BP) that solve-field writes, and pixels into RA, Dec through the forward terms (A, B).

Inputs: a header (path or dict). Outputs: numpy arrays of positions. Recipe entries: none of its own (the caller records
which solution it used)."""
import numpy as np


def read_header(path):
    """Cards of the first FITS header as a dict (numbers parsed, strings unquoted)."""
    buf = open(path, 'rb').read(); cards = {}; pos = 0
    while pos < len(buf):
        block = buf[pos:pos + 2880]; pos += 2880
        for i in range(0, 2880, 80):
            c = block[i:i + 80].decode('ascii', 'replace'); key = c[:8].strip()
            if key == 'END': return cards
            if c[8:10] == '= ':
                v = c[10:].strip()
                if v.startswith("'"): v = v[1:v.index("'", 1)].strip()
                else:
                    v = v.split('/')[0].strip()
                    if v in ('T', 'F'): v = v == 'T'
                    else:
                        try: v = int(v)
                        except ValueError:
                            try: v = float(v.replace('D', 'E'))
                            except ValueError: pass
                cards[key] = v
    return cards


class TanSip:
    def __init__(self, hdr):
        h = read_header(hdr) if isinstance(hdr, str) else dict(hdr)
        self.h = h
        self.crval = np.radians([float(h['CRVAL1']), float(h['CRVAL2'])])
        self.crpix = np.array([float(h['CRPIX1']), float(h['CRPIX2'])])
        self.cd = np.array([[h['CD1_1'], h['CD1_2']], [h['CD2_1'], h['CD2_2']]], float)
        self.cdi = np.linalg.inv(self.cd)
        self.sip = {n: self._poly(h, n) for n in ('A', 'B', 'AP', 'BP')}

    @staticmethod
    def _poly(h, n):
        o = int(h.get(n + '_ORDER', 0))
        return [(i, j, float(h.get('%s_%d_%d' % (n, i, j), 0.0))) for i in range(o + 1) for j in range(o + 1 - i)] if o else []

    @staticmethod
    def _ev(terms, u, v):
        out = np.zeros_like(u, float)
        for i, j, c in terms:
            if c: out += c * u ** i * v ** j
        return out

    def world2pix(self, ra, dec):
        """RA, Dec (deg) -> 0-based array (x, y)."""
        ra, dec = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
        a0, d0 = self.crval
        cosc = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(ra - a0)
        xi = np.cos(dec) * np.sin(ra - a0) / cosc
        eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(ra - a0)) / cosc
        X, Y = np.degrees(xi), np.degrees(eta)
        U = self.cdi[0, 0] * X + self.cdi[0, 1] * Y; V = self.cdi[1, 0] * X + self.cdi[1, 1] * Y
        u = U + self._ev(self.sip['AP'], U, V); v = V + self._ev(self.sip['BP'], U, V)
        return u + self.crpix[0] - 1, v + self.crpix[1] - 1

    def pix2world(self, x, y):
        u = np.asarray(x, float) + 1 - self.crpix[0]; v = np.asarray(y, float) + 1 - self.crpix[1]
        U = u + self._ev(self.sip['A'], u, v); V = v + self._ev(self.sip['B'], u, v)
        X = np.radians(self.cd[0, 0] * U + self.cd[0, 1] * V); Y = np.radians(self.cd[1, 0] * U + self.cd[1, 1] * V)
        a0, d0 = self.crval
        rho = np.hypot(X, Y); c = np.arctan(rho)
        with np.errstate(invalid='ignore', divide='ignore'):
            dec = np.where(rho == 0, d0, np.arcsin(np.cos(c) * np.sin(d0) + Y * np.sin(c) * np.cos(d0) / np.where(rho == 0, 1, rho)))
            ra = a0 + np.arctan2(X * np.sin(c), rho * np.cos(d0) * np.cos(c) - Y * np.sin(d0) * np.sin(c))
        return np.degrees(ra) % 360, np.degrees(dec)
