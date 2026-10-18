"""Step 13: delete the big intermediates once the deliverables exist (the stack arrays, the work copy of the flat, the
hot map, the 16-bit stretches); keep the steps' JSON, the logs, the small check pictures and the plate solve.
(Trial: the trial's copy of the flat, <night>/ngc891-coadd/flat/, goes too: it is the night's flat rebuilt, identical to <night>/flat/.)"""
import os, glob
from common import *

need = [os.path.join(OUT, f) for f in (NAME + '-stack.tif', NAME + '.jpg', NAME + '-field.jpg', 'recipe.json')] + [os.path.join(FINAL, f) for f in (NAME + '.png', NAME + '.jpg', NAME + '.json')] + [W('step14_compare.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W(NAME + '-stretched.png'), W('single-stretched.png'), W(NAME + '-crop.png')] + glob.glob(W('solve/*.fits')):
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))

import shutil
if os.path.isdir(FLAT_DIR) and os.path.abspath(FLAT_DIR) != os.path.abspath(os.path.join(NIGHT, 'flat')):
    freed2 = sum(os.path.getsize(os.path.join(FLAT_DIR, f)) for f in os.listdir(FLAT_DIR)); shutil.rmtree(FLAT_DIR); print('and the trial copy of the flat, %.2f GB' % (freed2 / 1e9))
