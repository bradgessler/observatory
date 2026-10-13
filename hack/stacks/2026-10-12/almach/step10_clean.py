"""Step 10: delete the intermediates once the deliverables exist (the crops, the stack arrays, the 16-bit stretch); keep the steps' JSON,
the logs and the plate solve."""
import glob
from common import *

FINAL = os.path.join(NIGHT, 'final')
need = [os.path.join(OUT, f) for f in ('almach-stack.tif', 'almach-stack-northup.tif', 'recipe.json')] + [os.path.join(FINAL, f) for f in ('almach.png', 'almach.jpg', 'almach.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + [W('almach-stretched.png'), W('solve/centring.fits')]:
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
print('freed %.1f MB' % (freed / 1e6))
