---
name: publish-observations
description: Put a night's finished pictures on the website as an observing session — the observations/ folder for the night, the session page (location, sky, equipment), the grid of pictures on black, a page per picture (plain, annotated with facts, for photographers), checked at desktop and phone widths, then published to the public site. Use when the user asks to publish, post or add pictures or a night to the site, or to change the Observations pages.
---

# Publish a night's observations

The site has a part for observations, grouped by night. A night's page is
its pictures on black; each opens a page with the plain picture up top, then
the annotated one with the facts, then the part for photographers. First
done for the night of 3 October 2026:
https://bradgessler.github.io/observatory-blog/observations/2026-10-03/

Before this: `stack-pictures`, `finish-pictures`, `annotate-pictures`.
After it: `share-cards` for the link previews.

## Where things are

    observations/<date>/session.md      the night, written by hand
    observations/<date>/objects.json    each picture's words, written by annotate.py --site
    observations/<date>/images/         every size the pages use, written by annotate.py --site
    observations/COPYRIGHT.md           the pictures and words are Brad Gessler's, all rights reserved
    apps/controller/lib/mix/tasks/site.build.ex   the builder: `mix site.build` writes _site/
    apps/controller/test/mix/tasks/site_build_test.exs
    bin/publish-blog, .github/workflows/blog.yml  the publish, by hand and from main

`observations/` is self-contained on purpose. It is meant to move to its own
repository later, probably bradgessler.com, and its copyright notice travels
with it. Do not make pages depend on anything outside the folder but the
builder.

## Steps

1. **Export**: in the night's folder,
   `python annotate.py --site <repo>/observations/<date>`. It writes, per
   picture: full size, a 1600-wide copy, a thumbnail, the labelled picture,
   the frames picture for a mosaic, a card crop for a tiny subject, and the
   entry in `objects.json`.
2. **Write `session.md`**. Front matter is `title`, `date`, `summary`, then
   one line per fact about the night; each key is the label the page shows,
   in the order written:

       Location: San Francisco Bay Area. A yard at home, with a big tree to the west
       Sky: ...
       Telescope: ...
       Camera: ...
       Field: ...
       Mount: ...
       Computer: ...
       Frames: ...
       Processing: ...

   Under it, a few short paragraphs in Brad's voice. Only things that
   happened; use his words from the night where you have them. He reads this
   as himself, so tell him you wrote it and ask him to check it.
3. **Build and test**: `mix site.build` at the root;
   `mix test test/mix/tasks/site_build_test.exs` in `apps/controller`.
4. **Look at it**: `tools/preview.sh <folder>` draws every page of the night
   at desktop width, at phone width, and its share card, with headless
   Chrome. Read the PNGs. Never open the pages in the app's browser pane: it
   stops the session on a permission prompt.
5. **Publish** (below).
6. **Check the live site** with curl: the pages answer 200, the pictures
   load, the `og:image` is right.

## A night published as it goes

Brad, 13 October 2026: "the plan gets published... each page could just be a
placeholder... and then as observations complete... you just publish each
observation." First done that night: eleven targets on the menu, ten
pictures published one at a time between 02:30 and 05:30 while he slept.

- **`observations/<date>/plan.json`** beside `session.md`: the targets in
  order, each with `slug`, `title`, `sub`, `what` (a sentence or two), and
  `state`: `planned`, `observing`, `processing`, `published` or `skipped`,
  with an optional short `note` ("30 frames"). The builder draws it as "On
  the menu" under the night's pictures, and gives a target with no picture
  yet a page saying where it stands. A target whose slug is in
  `objects.json` is published whatever the plan file says. **The slug in
  the plan and the key in `annotate.py`'s `targets()` must be the same.**
- **Publish the plan before the first picture exists**, then again at every
  change: the telescope moves on (the one it left is `processing`, the next
  `observing`), a picture is annotated (`published`), a target is skipped.
- **`tools/publish.sh check`** builds, lays the site over a fresh clone and
  prints what would change; **`tools/publish.sh push "message"`** does the
  same and pushes. Only `observations/<date>/…`, `observations/index.html`,
  `index.html` and `style.css` should change. It stops loudly when the
  build refuses.
- **One pipeline per picture, in this order:** a stacking agent per target
  as soon as the telescope leaves it (`stack-pictures`; give it the
  night's newest finished pipeline as its template and a time limit), then
  one annotating agent kept for the whole night and sent each finished
  picture in turn (`annotate-pictures`; it keeps the night's
  `annotate.py`), then look at the labelled picture yourself, then publish.
  Disk: one or two stacks at a time; each needs under 1 GB when RAWs are
  read in place.
- **No clock times in the plan or the pages.** States, not a schedule.
- **Write `session.md` twice:** once before the night (what is planned),
  and again at the end as what happened. Tell Brad you wrote it.

Things that went wrong that night, so they do not again:

- **How high a named object climbs is the telescope's latitude to half a
  degree**, clock time or not. Altitudes go to the nearest ten degrees at
  most ("about 80 degrees up", "nearly overhead").
- **The privacy guard refuses innocent numbers** that match the site's
  latitude or longitude to one decimal ("noise 37.9 DN"). Reword the number;
  never loosen the guard.
- **A share card's words sit at the foot by default.** When the subject is
  at the foot, set `CARD_TEXT[slug] = "top"` in `annotate.py`. Look at
  every card on a contact sheet before the last publish.
- **GitHub Pages serves the old page for about ten minutes** after a push:
  a state that looks stale on the live site usually is not.

## What the pages must do

- Plain pictures on true black, whatever the reader's theme.
- The night's grid shows every picture whole (contain, not cover); the first
  leads at twice the size where there is room for three across.
- **A phone is a first-class reader.** Pictures run edge to edge. A picture
  with names on it is too small to read at 390 px, so it pans sideways at a
  readable size, with one line saying so. Tapping any picture opens the full
  file. Check with the phone frame in `preview.sh`: a bare 390 px Chrome
  window is clamped to 500 and lies.
- A phone gets the 1600-wide copy (`srcset`); a retina laptop gets the full
  picture. Nothing is ever shown above its own pixels.
- Every page: the credit, how it was made, and "© year Brad Gessler".
- Words are HTML, not baked into pictures, so they are read by a screen
  reader, wrap on a phone and can be selected.

## Nothing published places the telescope

The builder refuses a post or a night whose text names the configured town
or gives its coordinates to a decimal, and strips every image's metadata.
It cannot see this one: **an altitude with a clock time and a named object
is a position line.** `annotate-pictures` keeps clock times out of the
words; check `objects.json` and `session.md` for "UTC" before publishing.

## Publishing

`bin/publish-blog` builds and pushes `_site/` to the public repository
`bradgessler/observatory-blog`. From a Claude session on the Mac Studio its
ssh remote is refused, so do its steps by hand over HTTPS with the signed-in
`gh`:

    git -c credential.helper= -c credential.helper='!gh auth git-credential' \
        clone https://github.com/bradgessler/observatory-blog.git "$PUB"
    # replace everything but .git with _site/, then LOOK: git -C "$PUB" status --short
    git -C "$PUB" config http.postBuffer 157286400     # a night's pictures are over the default
    git -C "$PUB" commit -m "..." && git -C "$PUB" -c credential.helper= -c credential.helper='!gh auth git-credential' push

Guard every destructive line with the clone's own path (`[ -d "$PUB/.git" ]`,
`git -C`, `find "$PUB"`), never a bare `cd && rm`: a failed clone once left
the shell in the working tree with the delete next in line.

Only the expected files should change: `observations/…`, `index.html`,
`style.css`. If a post's page changes, find out why first.

CI publishes from `main` whenever `posts/`, `observations/` or the builder
change there. A night published from a branch and not merged is wiped at the
next CI publish. Commit and merge, or say plainly that it is not durable.

## Do not

- run `mix format` on `site.build.ex`: the file keeps long lines and the
  formatter rewrites all of it;
- commit or push the private repository unless asked;
- put a picture on the site that the user has not seen.
