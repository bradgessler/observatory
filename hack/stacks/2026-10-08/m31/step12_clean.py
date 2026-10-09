"""Step 12: delete the big intermediates once the pictures and the recipe exist (the cached planes, the stacks and
their subsets, the stretched intermediates). Kept: every JSON, the logs, the small flat and dust maps and their
previews, the hot-pixel map, so that the recipe's numbers can be checked without the 5 GB."""
import os, glob, shutil
from common import *

need = [os.path.join(OUT, f) for f in ('m31.jpg', 'm31-1600.jpg', 'm31-stack.tif', 'recipe.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing: raise SystemExit('not cleaning: missing %s' % missing)
freed = 0
for p in [W('planes')] + glob.glob(W('?_*.npy')) + glob.glob(W('m31-*16bit.png')) + glob.glob(W('m31-*finished.png')) + glob.glob(W('m31-*finished.jpg')) + [W('unreg_median_G1.npy')]:
    if not os.path.exists(p): continue
    if os.path.isdir(p):
        freed += sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs); shutil.rmtree(p)
    else:
        freed += os.path.getsize(p); os.remove(p)
print('freed %.2f GB; work folder now %.1f MB' % (freed / 1e9, sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(WORK) for f in fs) / 1e6))
