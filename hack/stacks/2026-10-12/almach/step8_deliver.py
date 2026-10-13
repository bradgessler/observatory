"""Step 8: write the stack where it is kept. almach-stack.tif: the stack as the sensor saw it (not turned), float32, 3 planes
R, G (G1 and G2 together), B in raw DN above black, no white balance, sensor-pixel scale (0.388 arcsec), the primary at pixel (500, 550) of
1000 x 1100. almach-stack-northup.tif: the same planes turned once (Lanczos) so north is up and east left, cut to the picture's square, still linear.
Both are 'data'; the finished picture is made from them by step 7 and step 9 and the recipe says how."""
import numpy as np, tifffile
from common import *

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    d = np.load(W('stack.npz')); st = d['planes'].astype(np.float32)
    tifffile.imwrite(os.path.join(OUT, 'almach-stack.tif'), np.moveaxis(st, 0, -1), photometric='rgb', compression='zlib',
                     description='Almach 12/13 Oct 2026, a6000 + 8SE, 1/60 s ISO 400, sharpest frames drizzled at sensor scale; planes R, G, B in DN above black, linear, not turned; north is %.1f deg clockwise from up' % jload('step5_solve.json')['north_on_picture_deg_clockwise_from_up'])
    pl = np.load(W('almach-linear.npy'))
    tifffile.imwrite(os.path.join(OUT, 'almach-stack-northup.tif'), np.moveaxis(pl, 0, -1).astype(np.float32), photometric='rgb', compression='zlib',
                     description='the same planes turned once so north is up and east left, cut to %d x %d; linear DN above black' % pl.shape[1:])
    print('wrote', [(f, os.path.getsize(os.path.join(OUT, f)) // 1024) for f in ('almach-stack.tif', 'almach-stack-northup.tif')], 'KB')
