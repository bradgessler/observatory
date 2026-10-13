#!/bin/sh
# Build the site and publish it to the public repository over HTTPS with the signed-in gh (ssh is refused from a
# Claude session on the Mac Studio). Two steps, so the change is looked at before it goes:
#   publish.sh check              build, lay it over a fresh clone, print what would change. Nothing is pushed.
#   publish.sh push "message"     the same, then commit and push.
# Only observations/..., index.html and style.css should change for a night. If a post's page is in the list, find
# out why before pushing. Every destructive line names the clone's own path.
set -e
MODE=${1:-check}; MSG=${2:-"Rebuild the site"}
ROOT=$(cd "$(dirname "$0")/../../../.." && pwd); cd "$ROOT"
mix compile >/dev/null 2>&1
mix site.build | tail -1
PUB=$(mktemp -d "${TMPDIR:-/tmp}/observatory-blog.XXXXXX")/site
HELPER='!gh auth git-credential'
git -c credential.helper= -c credential.helper="$HELPER" clone -q --depth 1 https://github.com/bradgessler/observatory-blog.git "$PUB"
[ -d "$PUB/.git" ] || { echo "the clone failed: nothing touched"; exit 1; }
find "$PUB" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$ROOT/_site/." "$PUB"/
git -C "$PUB" add -A
echo "--- would change ($(git -C "$PUB" status --short | wc -l | tr -d ' ') paths):"
git -C "$PUB" status --short | sed 's/^/  /' | awk '{print} NR==60 {print "  ..."; exit}'
echo "--- by top folder:"; git -C "$PUB" status --short | awk '{print $2}' | sed 's|^"||' | awk -F/ '{print (NF>1 ? $1"/"$2 : $1)}' | sort | uniq -c | sort -rn | head -12
if [ "$MODE" = "push" ]; then
  git -C "$PUB" config http.postBuffer 157286400
  git -C "$PUB" -c user.name="Brad Gessler" -c user.email="$(git -C "$ROOT" config user.email)" commit -q -m "$MSG" || { echo "nothing to publish"; exit 0; }
  git -C "$PUB" -c credential.helper= -c credential.helper="$HELPER" push -q
  echo "published: https://bradgessler.github.io/observatory-blog/ ($(git -C "$PUB" rev-parse --short HEAD))"
fi
[ -d "$PUB/.git" ] && rm -rf "$PUB"
