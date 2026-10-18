"""Step 15: once the deliverables exist, delete the big intermediates (planes, cubes, stacks as .npy) from work/; keep
the JSON, the logs, the linear TIF and the pictures. CLEAN=0 in run_all.sh keeps everything."""
import glob, os
from common import *
need = [os.path.join(OUT, 'm27-stack.tif'), os.path.join(FINAL, 'recipe.json')] + [os.path.join(FINAL, NAME + e) for e in ('.png', '.jpg', '.json')]
missing = [f for f in need if not os.path.exists(f)]
if missing: raise SystemExit('not cleaning: missing %s' % missing)
gone = 0
for f in glob.glob(W('*.npy')) + glob.glob(W('*.npz')) + glob.glob(W('flatcheck/*.npz')) + [W('m27-stretched.png'), W('single-stretched.png'), W('m27-crop.png')] + glob.glob(W('solve/*.fits')):
    if os.path.exists(f): gone += os.path.getsize(f); os.remove(f)
print('deleted %.2f GB of intermediates from %s' % (gone / 1e9, WORK))
