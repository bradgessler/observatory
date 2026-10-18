"""Step 13: delete the work space (stacks, moon field, JSON) once the pictures and recipe.json are delivered. The RAWs are
never touched. CLEAN=0 in run_all.sh keeps it."""
import shutil
from common import *
if __name__ == '__main__':
    n = sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(WORK) for f in fs) if os.path.isdir(WORK) else 0
    shutil.rmtree(WORK, ignore_errors=True); print('deleted %s (%.0f MB)' % (WORK, n / 1e6))
