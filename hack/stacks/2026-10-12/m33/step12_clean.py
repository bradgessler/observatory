"""Step 12: delete the big intermediates once the deliverables exist (the stack arrays, the flat, the hot map, the
16-bit stretches); keep the steps' JSON, the logs, the small check pictures and the plate solve."""
import os, glob
from common import *

FINAL = os.environ.get('M33_FINAL', os.path.join(NIGHT, 'final'))
need = [os.path.join(OUT, f) for f in ('m33-stack.tif', 'm33.jpg', 'm33-1600.jpg', 'recipe.json')] + [os.path.join(FINAL, f) for f in ('m33.png', 'm33.jpg', 'm33.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W('m33-stretched.png'), W('single-stretched.png'), W('solve/stack.fits')]:
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))
