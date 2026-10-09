"""Step 12: delete the big intermediates once the deliverables exist (the cached colour planes and the stack arrays);
keep the scripts' JSON, the logs, the small check pictures, the measured blur and the plate solve."""
import os, glob, shutil
from common import *

need = [os.path.join(OUT, f) for f in ('m33-stack.tif', 'm33.jpg', 'm33-1600.jpg', 'recipe.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing:
    raise SystemExit('deliverables missing, nothing deleted: %s' % missing)
freed = 0
if os.path.isdir(W('planes')):
    freed += sum(os.path.getsize(f) for f in glob.glob(W('planes/*')))
    shutil.rmtree(W('planes'))
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')):
    if os.path.basename(f) in ('psf.npy',): continue
    freed += os.path.getsize(f); os.remove(f)
print('freed %.2f GB' % (freed / 1e9))
