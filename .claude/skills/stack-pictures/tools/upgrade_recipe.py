"""Bring a stack's recipe.json to the schema observatory.recipe/1 without changing any picture.

What it does: reads a recipe in the free shape the pipelines wrote before the schema (hack/stacks/<night>/<target>/
final/recipe.json) and writes the same facts in the schema's shape:
  schema, id                 observatory.recipe/1; the SHA-256 of the recipe's substance (obsmeta.recipe_id)
  target                     {name (SIMBAD), ids, title, ra_deg, dec_deg, text: the old prose}
  night, made, reproduce     as before (night: {date, text}); Saturn's recipe had no `made`: the time of the commit
                             that first delivered it, and it says so
  roots                      where relative paths start: repo, night (the night's work folder), stills
  software, git              the tool versions in this environment (installed before the night and unchanged since,
                             checked from the packages' install dates when this was run), the repository's commit
  inputs                     every frame the pipeline considered: name, observing night, folder, the RAW's SHA-256 from
                             its sidecar, the sidecar's and the plate solve's own SHA-256, used or not and why, its
                             weight, and what the old recipe said about it (turn, kind, dither, fate ...). With
                             --verify-raws every RAW is hashed and must match its sidecar
  calibration                flat, dark, sensor map: what was applied, with paths and SHA-256 where there is a file
  steps                      the old steps unchanged, each given a one-line `history` (the FITS HISTORY); a recipe
                             whose numbers sat in top-level sections (Saturn) gets one step per section, in order
  outputs                    every file the pipeline delivered: file, root, kind, SHA-256, bytes
  the pipeline's own keys    (summary, template, ...) kept as they were
Absolute paths become relative to the repository or ~/.observatory. No site, no latitude, no longitude: the inputs
name the frames, and the frames' sidecars carry the site.

The old keys `files`, `frames` (a list), `dropped`, `every_frame` and `delivered_sha256` are folded into inputs and
outputs; nothing is lost (every per-frame field is kept on that frame's input entry).

Library use (a pipeline's metadata step):  new = upgrade(old, ctx)  where ctx is a dict:
  target {name, ids, title, ra_deg, dec_deg}, night (date), folders [where the frames are], roots {name: path},
  calibration {...}, history {step name: line}, sections [top-level keys that are steps, in order],
  outputs [(path, kind, root)], scripts (the pipeline folder), made (when the recipe has none), verify_raws (bool).
CLI: python upgrade_recipe.py <recipe.json> --ctx <ctx.json> [--out new.json] [--verify-raws]"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obsmeta as om

OLD_FRAME_KEYS = ('file', 'frame', 'stamp', 'arw_sha256', 'sha256')


def _selection(old):
    """(used {stamp: numbers}, rejected {stamp: numbers with why}) from the step whose numbers have used and rejected."""
    for s in old.get('steps') or []:
        n = s.get('numbers')
        if isinstance(n, dict) and 'used' in n and 'rejected' in n:
            u, r = n['used'], n['rejected']
            used = u if isinstance(u, dict) else {x['stamp']: x for x in u}
            rej = r if isinstance(r, dict) else {x['stamp']: x for x in r}
            return used, rej
    return None, None


def _frame_list(old, folders):
    """[(frame name or stamp, the old recipe's own fields for it)] in the old recipe's order."""
    if isinstance(old.get('frames'), list):
        return [(f.get('file') or f.get('stamp'), f) for f in old['frames']]
    if isinstance(old.get('every_frame'), list):
        out = [(f['frame'], f) for f in old['every_frame']]
        moons = (old.get('frames') or {}).get('moons') if isinstance(old.get('frames'), dict) else None
        out += [(m, dict(role='moons')) for m in moons or []]
        return out
    used, rej = _selection(old)
    if used is None: raise SystemExit('no frame list in this recipe (frames, every_frame or a selection step)')
    return [(st, {}) for st in sorted(set(used) | set(rej))]


def inputs_of(old, ctx):
    used, rej = _selection(old)
    dropped = {}
    if isinstance(old.get('dropped'), dict):
        for v in old['dropped'].values():
            if isinstance(v, dict): dropped.update(v)
    if isinstance((old.get('summary') or {}).get('dropped'), dict): dropped.update(old['summary']['dropped'])
    out = []
    for name, own in _frame_list(old, ctx['folders']):
        stem = om.find_frame(name, ctx['folders'])
        if not stem: raise SystemExit('frame %s: no sidecar in %s' % (name, ctx['folders']))
        rec = om.read_frame(stem)
        stamp = rec['stem'][:15]
        old_sha = own.get('arw_sha256') or own.get('sha256')
        if old_sha and old_sha != rec['sha256']: raise SystemExit('%s: the recipe says sha256 %s, the sidecar %s' % (name, old_sha, rec['sha256']))
        if ctx.get('verify_raws'):
            p = os.path.join(os.path.dirname(rec['path_stem']), rec['name'])
            if om.sha256_file(p) != rec['sha256']: raise SystemExit('%s: the RAW does not match its sidecar\'s sha256' % p)
        extra = {k: v for k, v in own.items() if k not in OLD_FRAME_KEYS}
        why = None; weight = None
        if 'fate' in own:
            is_used = own['fate'] == 'kept'; why = None if is_used else own['fate']; role = 'planet'
            extra.pop('fate'); extra['role'] = role
        elif own.get('role') == 'moons':
            is_used = True; extra['role'] = 'moons'; why = None
        elif used is not None:
            is_used = stamp in used and stamp not in dropped
            if stamp in rej: why = rej[stamp].get('why')
            elif stamp in dropped: why = dropped[stamp]
            elif not is_used: why = 'not in the selection'
            if stamp in used: weight = used[stamp].get('weight')
        else:
            is_used = stamp not in dropped; why = dropped.get(stamp)
        out.append(om.input_entry(rec, used=is_used, why=why, weight=weight, **extra))
    return out


def upgrade(old, ctx):
    """old recipe dict -> observatory.recipe/1 dict (see the module's docstring)."""
    if old.get('schema') == om.RECIPE_SCHEMA:
        return old
    r = {}
    t = dict(ctx['target'])
    t['text'] = old.get('target') if isinstance(old.get('target'), str) else old.get('what')
    r['target'] = t
    nt = old.get('night')
    r['night'] = dict(date=ctx['night'], text=nt) if nt else dict(date=ctx['night'])
    if old.get('made'): r['made'] = old['made']
    else: r['made'] = ctx['made']; r['made_from'] = ctx.get('made_from', 'this recipe had no time of its own')
    r['reproduce'] = old.get('reproduce') or ('%s/run_all.sh' % om.rel(ctx['scripts']) + ('; ' + old['scripts'] if old.get('scripts') else ''))
    r['roots'] = ctx['roots']
    sw = om.software()
    r['software'] = sw
    r['software_note'] = ctx.get('software_note', 'the versions in this environment when the recipe was brought to the schema; the packages were installed before the night and not changed since')
    if isinstance(old.get('tools'), dict) and old['tools'].get('note'): r['method_note'] = old['tools']['note']
    r['git'] = om.git_info(ctx['scripts'])
    r['inputs'] = inputs_of(old, ctx)
    r['calibration'] = ctx.get('calibration') or {}
    hist = ctx.get('history') or {}
    if old.get('steps'):
        steps = [dict(s) for s in old['steps']]
    else:
        steps = [dict(step=label, key=key, numbers=old[key]) for label, key in ctx['sections'] if key in old]
    for s in steps:
        if s['step'] in hist: s['history'] = hist[s['step']]
    r['steps'] = steps
    r['outputs'] = [om.output_entry(p, kind, root, ctx['roots']) for p, kind, root in ctx.get('outputs') or []]
    if old.get('delivered_sha256'):                          # Saturn's own hashes: the files must still be those
        for f, h in old['delivered_sha256'].items():
            o = [x for x in r['outputs'] if x['file'].endswith(f.split('/')[-1])]
            if o and o[0]['sha256'] != h: raise SystemExit('%s: delivered %s, now %s' % (f, h, o[0]['sha256']))
    folded = {'target', 'what', 'night', 'made', 'reproduce', 'scripts', 'tools', 'files', 'dropped', 'every_frame', 'delivered_sha256', 'steps'}
    if isinstance(old.get('frames'), list): folded.add('frames')
    folded |= {key for _, key in ctx.get('sections') or []}
    for k, v in old.items():
        if k not in folded: r[k] = v
    return om.finish_recipe(r, ctx['scripts'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('recipe'); ap.add_argument('--ctx', required=True); ap.add_argument('--out'); ap.add_argument('--verify-raws', action='store_true')
    a = ap.parse_args()
    ctx = json.load(open(a.ctx)); ctx['verify_raws'] = a.verify_raws or ctx.get('verify_raws')
    new = upgrade(json.load(open(a.recipe)), ctx)
    bad = om.check_recipe(new)
    om.dump_recipe(new, a.out or a.recipe)
    print('%s: %d inputs (%d used), %d steps, %d outputs; %s' % (a.out or a.recipe, len(new['inputs']), sum(i['used'] for i in new['inputs']), len(new['steps']), len(new['outputs']), 'conforms' if not bad else bad))
