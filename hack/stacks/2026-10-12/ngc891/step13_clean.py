"""Step 13: delete the big intermediates once the deliverables exist (the stack arrays, the work copy of the flat, the
hot map, the 16-bit stretches); keep the steps' JSON, the logs, the small check pictures and the plate solve.
The night's flat in <night>/flat/ is a deliverable and stays."""
import os, glob
from common import *

FINAL = os.environ.get('N891_FINAL', os.path.join(NIGHT, 'final'))
need = [os.path.join(OUT, f) for f in ('ngc891-stack.tif', 'ngc891.jpg', 'ngc891-field.jpg', 'recipe.json')] + [os.path.join(FINAL, f) for f in ('ngc891.png', 'ngc891.jpg', 'ngc891.json')] + [os.path.join(FLAT_DIR, f) for f in ('flat_planes.npz', 'flat.json', 'README.txt')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W('ngc891-stretched.png'), W('single-stretched.png'), W('ngc891-crop.png')] + glob.glob(W('solve/*.fits')):
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))
