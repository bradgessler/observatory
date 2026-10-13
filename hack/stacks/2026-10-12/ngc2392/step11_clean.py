"""Step 11: delete the big intermediates once the deliverables exist (the stack arrays, the hot map, the 16-bit
stretch); keep the steps' JSON, the logs and the plate solves. Nothing that came from the camera and nothing in
<night>/flat/ is touched."""
import glob, os
from common import *

need = [os.path.join(OUT, f) for f in ('ngc2392-stack.tif', 'ngc2392.jpg', 'recipe.json')] + [os.path.join(FINAL, f) for f in ('ngc2392.png', 'ngc2392.jpg', 'ngc2392.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
for f in glob.glob(W('*.npy')) + [W('ngc2392-stretched.png')] + glob.glob(W('solve/*.fits')) + glob.glob(W('solve/*.xy')) + glob.glob(W('solve/*.axy')):
    if os.path.exists(f):
        freed += os.path.getsize(f); os.remove(f)
left = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
print('freed %.2f GB; the target folder now holds %.1f MB' % (freed / 1e9, left / 1e6))
