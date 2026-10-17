"""The little of FITS needed here (no astropy on this machine): write a 2-D 16-bit image, read a header's cards."""
import numpy as np


def write_image(path, img):
    """16-bit signed FITS, rows top to bottom as in the array (FITS pixel (x + 1, y + 1) = img[y, x])."""
    im = np.clip(np.nan_to_num(np.asarray(img, np.float64)), -32768, 32767).round().astype('>i2')
    cards = ['SIMPLE  =                    T', 'BITPIX  =                   16', 'NAXIS   =                    2', 'NAXIS1  = %20d' % im.shape[1], 'NAXIS2  = %20d' % im.shape[0], 'END']
    hdr = ''.join(c.ljust(80) for c in cards); hdr = hdr.ljust((len(hdr) + 2879) // 2880 * 2880)
    data = im.tobytes(); data += b'\0' * ((2880 - len(data) % 2880) % 2880)
    open(path, 'wb').write(hdr.encode() + data)


def read_header(path):
    """Cards of the first header as a dict (numbers parsed, strings unquoted)."""
    buf = open(path, 'rb').read(); cards = {}; pos = 0
    while True:
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
