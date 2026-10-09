"""The little of FITS that is needed here (no astropy on this machine): write a 2-D image, read a header, read a
binary table with scalar numeric columns (astrometry.net's .corr file)."""
import numpy as np


def write_image(path, img):
    """16-bit signed FITS, rows top to bottom as in the array (FITS pixel (x + 1, y + 1) = img[y, x])."""
    im = np.asarray(img).astype('>i2')
    cards = ['SIMPLE  =                    T', 'BITPIX  =                   16', 'NAXIS   =                    2', 'NAXIS1  = %20d' % im.shape[1], 'NAXIS2  = %20d' % im.shape[0], 'END']
    hdr = ''.join(c.ljust(80) for c in cards); hdr = hdr.ljust((len(hdr) + 2879) // 2880 * 2880)
    data = im.tobytes(); data += b'\0' * ((2880 - len(data) % 2880) % 2880)
    open(path, 'wb').write(hdr.encode() + data)


def _header(buf, pos):
    cards = {}
    while True:
        block = buf[pos:pos + 2880]; pos += 2880
        end = False
        for i in range(0, 2880, 80):
            c = block[i:i + 80].decode('ascii', 'replace'); key = c[:8].strip()
            if key == 'END': end = True; break
            if c[8:10] == '= ':
                v = c[10:].split('/')[0].strip() if not c[10:].lstrip().startswith("'") else c[10:].strip()
                if v.startswith("'"): v = v[1:v.index("'", 1)].strip()
                elif v in ('T', 'F'): v = v == 'T'
                else:
                    try: v = int(v)
                    except ValueError:
                        try: v = float(v.replace('D', 'E'))
                        except ValueError: pass
                cards[key] = v
        if end: return cards, pos


def read_header(path, hdu=0):
    buf = open(path, 'rb').read(); pos = 0
    for k in range(hdu + 1):
        h, pos = _header(buf, pos)
        if k == hdu: return h
        size = abs(h.get('BITPIX', 8)) // 8 * int(np.prod([h['NAXIS%d' % (i + 1)] for i in range(h.get('NAXIS', 0))])) if h.get('NAXIS', 0) else 0
        size += h.get('PCOUNT', 0); pos += (size + 2879) // 2880 * 2880


def read_bintable(path, hdu=1):
    buf = open(path, 'rb').read(); pos = 0
    for k in range(hdu + 1):
        h, pos = _header(buf, pos)
        size = abs(h.get('BITPIX', 8)) // 8 * int(np.prod([h['NAXIS%d' % (i + 1)] for i in range(h.get('NAXIS', 0))])) if h.get('NAXIS', 0) else 0
        if k == hdu: break
        pos += (size + h.get('PCOUNT', 0) + 2879) // 2880 * 2880
    fmt = {'D': '>f8', 'E': '>f4', 'J': '>i4', 'K': '>i8', 'I': '>i2', 'B': 'u1', 'L': 'u1'}
    dt = []
    for i in range(1, h['TFIELDS'] + 1):
        f = str(h['TFORM%d' % i]).strip(); rep = f[:-1]; code = f[-1]
        rep = int(rep) if rep else 1
        name = str(h['TTYPE%d' % i]).strip()
        if code == 'A': dt.append((name, 'S%d' % rep))
        elif rep == 1: dt.append((name, fmt[code]))
        else: dt.append((name, fmt[code], (rep,)))
    arr = np.frombuffer(buf[pos:pos + h['NAXIS1'] * h['NAXIS2']], dtype=np.dtype(dt))
    return {n: np.array(arr[n]) for n in arr.dtype.names}
