"""Step 13: the big intermediates go once the deliverables exist (planes, stacks, the hot-pixel map, the stretched PNGs,
the solver's FITS images). Kept: logs, the small JSON records of every step, the finished picture's own JSON."""
import glob, os, shutil
from common import *

for f in ('m1.jpg', 'm1-single-vs-stack.jpg', 'm1-stack.tif', 'recipe.json'):
    assert os.path.exists(os.path.join(OUT, f)), f
freed = 0
for p in [W_('planes')] + glob.glob(W_('*.npy')) + glob.glob(W_('*.png')) + glob.glob(W_('*.jpg')) + glob.glob(W_('solve/*.fits')):
    if os.path.isdir(p):
        freed += sum(os.path.getsize(os.path.join(p, f)) for f in os.listdir(p)); shutil.rmtree(p)
    elif os.path.exists(p):
        freed += os.path.getsize(p); os.remove(p)
print('freed %.2f GB; left in work:' % (freed / 1e9), sorted(os.listdir(WORK)))
