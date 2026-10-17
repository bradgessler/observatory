"""Step 13: delete the big intermediates once the deliverables exist (the stack arrays, the work copy of the flat, the
hot map, the 16-bit stretches); keep the steps' JSON, the logs, the small check pictures and the plate solve.
The flat the control builds (work/night-flat/) goes too; the flats under <night>/flat-* stay."""
import os, glob
from common import *

need = [os.path.join(OUT, f) for f in ('ngc891-stack.tif', 'ngc891.jpg', 'ngc891-field.jpg', 'recipe.json')] + [os.path.join(FINAL, NAME + e) for e in ('.png', '.jpg', '.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W('ngc891-stretched.png'), W('single-stretched.png'), W('ngc891-crop.png')] + glob.glob(W('solve/*.fits')) + glob.glob(os.path.join(FLAT_DIR, '*.npz')):
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))
