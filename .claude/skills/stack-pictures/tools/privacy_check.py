"""Before a commit: does anything about to go into the public repository give the telescope's site away?

What it does: reads the site from config/site.secret.exs (untracked; the only place the real values live) and looks in
the given files (default: the files staged for commit) for
  * any number within 0.05 degrees of the site's latitude or longitude (signed), and of their absolute values;
  * the site's name;
  * in JSON, any key that names a place (site, lat, lon, latitude, longitude, sitelat, sitelong, obsgeo-*).
Each finding is printed with its file, its JSON path (or line) and the text around it, with the matched value hidden.
A number that is near by coincidence (a noise level in DN in a recipe) is still reported: a person looks at it and
passes it with --allow <regex of JSON paths>. Exit status 0 when nothing was found (or all of it was allowed).

Binary files (pictures) are skipped: the site builder strips their metadata, and annotate.py writes none.
CLI: python privacy_check.py [files ...] [--allow REGEX ...]"""
import argparse, json, os, re, subprocess, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
NUM = re.compile(r'(?<![\w.])-?\d+\.\d+')
PLACE_KEY = re.compile(r'^(site|lat|lon|latitude|longitude|sitelat|sitelong|siteelev|obsgeo.*|elevation_m)$', re.I)


def site():
    s = open(os.path.join(REPO, 'config', 'site.secret.exs')).read()
    lat = float(re.search(r'lat:\s*(-?[\d.]+)', s).group(1)); lon = float(re.search(r'lon:\s*(-?[\d.]+)', s).group(1))
    m = re.search(r'name:\s*"([^"]+)"', s)
    return lat, lon, (m.group(1) if m else None)


def near(v, lat, lon, tol=0.05):
    if abs(v - lat) < tol or abs(v - lon) < tol: return 'signed'
    if abs(abs(v) - abs(lat)) < tol or abs(abs(v) - abs(lon)) < tol: return 'absolute'
    return None


def walk(o, path, out, lat, lon):
    if isinstance(o, dict):
        for k, v in o.items():
            if PLACE_KEY.match(str(k)) and v not in (None, {}, []): out.append(('place key', path + '/' + str(k), '%s = <%s>' % (k, type(v).__name__)))
            walk(v, path + '/' + str(k), out, lat, lon)
    elif isinstance(o, list):
        for i, v in enumerate(o): walk(v, '%s[%d]' % (path, i), out, lat, lon)
    elif isinstance(o, float) and not isinstance(o, bool):
        n = near(o, lat, lon)
        if n: out.append(('number near the site (%s)' % n, path, '<hidden>'))
    elif isinstance(o, str):
        for m in NUM.finditer(o):
            n = near(float(m.group()), lat, lon)
            if n: out.append(('number near the site in text (%s)' % n, path, o[max(0, m.start() - 40):m.start()] + '<hidden>' + o[m.end():m.end() + 20]))


def check_file(p, lat, lon, name):
    out = []
    try: t = open(p, encoding='utf-8').read()
    except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError): return out
    if name and name.lower() in t.lower(): out.append(('the site\'s name', 'text', '%s' % '<hidden>'))
    if p.endswith('.json'):
        try:
            walk(json.loads(t), '', out, lat, lon); return out
        except ValueError:
            pass
    for i, line in enumerate(t.splitlines(), 1):
        for m in NUM.finditer(line):
            n = near(float(m.group()), lat, lon)
            if n: out.append(('number near the site (%s)' % n, 'line %d' % i, line[max(0, m.start() - 40):m.start()].strip() + ' <hidden> ' + line[m.end():m.end() + 20].strip()))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='*'); ap.add_argument('--allow', action='append', default=[])
    a = ap.parse_args()
    files = a.files or [os.path.join(REPO, f) for f in subprocess.run(['git', '-C', REPO, 'diff', '--cached', '--name-only'], capture_output=True, text=True).stdout.split()]
    lat, lon, name = site()
    bad = 0; allowed = 0
    for f in files:
        for kind, where, ctx in check_file(f, lat, lon, name):
            ok = any(re.search(r, where) for r in a.allow)
            allowed += ok; bad += not ok
            print('%s %s: %s at %s: %s' % ('allowed' if ok else 'FOUND  ', os.path.relpath(f, REPO), kind, where, ctx))
    print('%d files checked: %d findings%s' % (len(files), bad, ', %d allowed by --allow' % allowed if allowed else ''))
    sys.exit(1 if bad else 0)
