"""Step 14: delete the big intermediates once the deliverables exist (the stack arrays, the work copy of the flat, the
hot map, the 16-bit stretches); keep the steps' JSON, the logs, the small check pictures and the plate solve.
Nothing in <night>/flat/ is touched: it is another stack's deliverable."""
import os, glob
from common import *

FINAL = os.environ.get('N2419_FINAL', os.path.join(NIGHT, 'final'))
need = [os.path.join(OUT, f) for f in ('ngc2419-stack.tif', 'ngc2419.jpg', 'ngc2419-field.jpg', 'recipe.json')] + [os.path.join(FINAL, f) for f in ('ngc2419.png', 'ngc2419.jpg', 'ngc2419.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W('ngc2419-stretched.png'), W('single-stretched.png'), W('ngc2419-crop.png')] + glob.glob(W('solve/*.fits')) + [os.path.join(SCR, '__pycache__', f) for f in (os.listdir(os.path.join(SCR, '__pycache__')) if os.path.isdir(os.path.join(SCR, '__pycache__')) else [])]:
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))
