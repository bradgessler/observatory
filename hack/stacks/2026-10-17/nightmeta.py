"""The night of 17 October 2026: what the four pipelines' metadata steps share (m27, m33, m42: step16_metadata.py;
saturn: step14_metadata.py). Each step brings its recipe to observatory.recipe/1 (tools/upgrade_recipe.py) and writes
the linear stack as <target>-stack.fits beside the TIF in the night's folder (tools/stack_fits.py), then adds the FITS
to the recipe's outputs. Nothing here changes a picture: the pictures, the TIF and the share set are hashed, not made.

Roots of the recipes' relative paths: repo (the repository), night (~/.observatory/nights/2026-10-17-a6000), stills
(~/.observatory/stills), nights (~/.observatory/nights)."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.abspath(os.path.join(HERE, '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
if TOOLS not in sys.path: sys.path.insert(0, TOOLS)
import obsmeta as om, stack_fits, upgrade_recipe

NIGHT_DATE = '2026-10-17'
NIGHT_DIR = os.path.expanduser('~/.observatory/nights/2026-10-17-a6000')
ROOTS = dict(repo='.', night='~/.observatory/nights/2026-10-17-a6000', stills='~/.observatory/stills', nights='~/.observatory/nights')
SHARE_SLUG = dict(m27='dumbbell-nebula', m33='triangulum-galaxy', m42='orion-nebula', saturn='saturn')


def flat_entry(flat_dir, how):
    """The flat a stack was divided by: its folder, the .npz's SHA-256, when it was made, and its master FITS if any."""
    npz = os.path.join(flat_dir, 'flat_planes.npz'); j = json.load(open(os.path.join(flat_dir, 'flat.json')))
    e = dict(applied=True, file=om.rel(npz), sha256=om.sha256_file(npz), made_utc=j.get('made_utc'), tool=om.rel(j.get('tool')), how=how)
    fz = os.path.join(flat_dir, 'flat_planes.fits')
    if os.path.exists(fz): e['fits'] = dict(file=om.rel(fz), sha256=om.sha256_file(fz))
    return e


def outputs(scripts, final, name, out_dir, extra=()):
    """(path, kind, root) of everything the pipeline delivered that is on disk: pictures, finish recipe, the TIF and the
    full field in the night folder, the pipeline's own share set and the night's share set."""
    o = []
    for f, kind in ((name + '.png', 'picture_png'), (name + '.jpg', 'picture_jpg'), (name + '.json', 'finish_recipe')):
        p = os.path.join(final, f)
        if os.path.exists(p): o.append((p, kind, 'repo'))
    for f, kind in ((name + '-stack.tif', 'stack_tif'), (name + '-field.png', 'field_png'), (name + '-field.jpg', 'field_jpg')):
        p = os.path.join(out_dir, f)
        if os.path.exists(p): o.append((p, kind, 'night'))
    sh = os.path.join(scripts, 'share')
    for f in sorted(os.listdir(sh)) if os.path.isdir(sh) else []:
        if f.endswith('.jpg'): o.append((os.path.join(sh, f), 'share_jpg', 'repo'))
    slug = SHARE_SLUG.get(os.path.basename(scripts))
    for suf in ('', '-annotated', '-how'):
        p = os.path.join(HERE, 'share', '%s%s.jpg' % (slug, suf))
        if os.path.exists(p): o.append((p, 'night_share_jpg', 'repo'))
    return o + list(extra)


def frames_of(recipe, role=None):
    """read_frame records of the inputs used (optionally of one role), and their weights (None if any is missing)."""
    used = [i for i in recipe['inputs'] if i['used'] and (role is None or i.get('role') == role)]
    recs = [om.read_frame(os.path.join(os.path.expanduser(i['folder']), os.path.splitext(i['name'])[0]), exif=True) for i in used]
    for i, r in zip(used, recs):
        assert r['sha256'] == i['sha256'], i['name']
    w = [i.get('weight') for i in used]
    return recs, (None if any(x is None for x in w) else w)


def add_fits_output(recipe, fits_path, step, scripts):
    """The FITS as an output of the recipe (its WCS, the solve and the checks with it), replacing an earlier one; the id
    does not change (outputs are not part of it)."""
    e = om.output_entry(fits_path, 'stack_fits', 'night', ROOTS)
    e['fits'] = {k: v for k, v in step.items() if k not in ('file', 'sha256', 'bytes')}
    recipe['outputs'] = [o for o in recipe['outputs'] if o.get('kind') != 'stack_fits'] + [e]
    return om.finish_recipe(recipe, scripts)


def report(recipe, step):
    bad = om.check_recipe(recipe)
    c = (step.get('wcs_check') or {}).get('all') or {}
    print('recipe: %d inputs (%d used), %d steps with %d HISTORY lines, %d outputs; id %s; %s' % (
        len(recipe['inputs']), sum(i['used'] for i in recipe['inputs']), len(recipe['steps']), len(om.history_lines(recipe)), len(recipe['outputs']), recipe['id'][:16],
        'conforms to %s' % om.RECIPE_SCHEMA if not bad else 'PROBLEMS %s' % bad))
    print('stack FITS: %s %s, %d cards, sha256 %s' % (step['file'], step['shape'], step['cards'], step['sha256'][:16]))
    if step.get('tif_check'): print('  the TIF is this array + %g, rounded and clipped: %s (values clipped high %d, low %d)' % (step['tif_check']['pedestal'], step['tif_check']['equal'], step['tif_check']['values_clipped_high'], step['tif_check']['values_clipped_low']))
    if step.get('solve'): print('  plate solve: %s, %d stars matched, rms %.3f px' % (step['solve']['index'], step['solve']['matched_stars'], step['solve']['match_rms_px']))
    if c: print('  WCS against Gaia DR3: %d stars, median %.3f px, p90 %.3f px, max %.3f px, mean offset (%.3f, %.3f) px; passed %s' % (c['n'], c['median_px'], c['p90_px'], c['max_px'], c['mean_dx_px'], c['mean_dy_px'], step['wcs_check']['passed']))
    if step.get('against_the_pipelines_own_solve'): print('  against the pipeline\'s own solve of the stack: max %.3f px, median %.3f px' % (step['against_the_pipelines_own_solve']['max_px'], step['against_the_pipelines_own_solve']['median_px']))
    if bad: raise SystemExit('the recipe does not conform: %s' % bad)
