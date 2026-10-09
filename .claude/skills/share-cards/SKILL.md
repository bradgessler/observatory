---
name: share-cards
description: Design, wire up and verify the link-preview cards OpenGraph+ (ogplus) draws for every page of the site — the picture edge to edge with its name and facts for a gallery page, a collage for a night, date and title beside the hero for a post. Use when the user mentions ogplus, OpenGraph+, og:image, share cards or link previews, when a card looks wrong or stale, or when a new kind of page needs a card.
---

# Share cards with OpenGraph+

OpenGraph+ (https://opengraphplus.com, the user's own product) loads a page
in a headless browser and photographs it as the page's `og:image`. Every
page of the site carries a card made for that: a `<template id="ogplus">`
that OpenGraph+ swaps in for the page's body. It is all in
`apps/controller/lib/mix/tasks/site.build.ex` (search for "share cards").

## How it is wired

- The site's connection is `@ogplus` in the builder
  (`https://mlghbepw.ogplus.net`, made with
  `ogplus site create bradgessler.github.io` on 4 October 2026). It is
  public: it is in every page's `og:image`, which is the connection URL
  followed by the page's path.
- `mix site.build --ogplus ""` builds without it; a page then shares with
  its own picture.
- Tags on a page with a card: `og:plus:viewport:width` 1200,
  `og:plus:style` (no margin, black), `og:plus:cache:max_age` 3600, and
  `og:plus:cache:etag`, a hash of the card, so it is drawn again only when
  it changes.
- The CLI is `ogplus` (`~/.terminalwire/bin/ogplus`). It needs the user
  signed in; `ogplus login` is theirs to run. The guide for an LLM is at
  https://opengraphplus.com/docs/html-css.md.

## The cards

| Page | Card |
|---|---|
| a picture, wider than tall | the picture edge to edge, a dark fade, title, subtitle and up to three short facts at the foot (at the head when the foot is the busy part: `CARD_TEXT` in annotate.py) |
| a picture, tall or square | the picture whole on the right, the words on the left |
| a tiny subject (Saturn) | a crop at the picture's own pixels (`CARD` in annotate.py), never an enlargement |
| a picture narrower than the card (the 600 to 800 px planetary nebulae of 8 October) | the picture whole on the right at no more than its own pixels, the words on the left (`native/4`) |
| a night, Observations, the home page | title and a line of words beside six of the pictures |
| a post | date and title beside its hero picture, shown whole (most heroes are phone screenshots, small and tall) |

Only facts of 36 characters or fewer make a card; the long ones belong on
the page.

## Rules a template must follow

- **Inline styles only.** The page's stylesheet does not reach a template.
  No classes. The tests check this.
- **The card's box is `100vw` by `100vh`, never `height:100%`.** OpenGraph+
  puts the template in a body of no set height, where `height:100%` is
  nothing: a card of absolutely placed parts came out blank, and the others
  overflowed. Inside that box, percentages work.
- Sizes in `vw`, so the card holds at any width.
- Relative image paths, from the page's own folder.
- Text over a picture gets a fade behind it and, for the small mark, a
  shadow.

## Verifying

1. **Locally**: `publish-observations/tools/preview.sh` draws each card at
   1200 x 630 in a body with no height, as OpenGraph+ does. A card that
   leans on `height:100%` shows broken there too.
2. **For real, after publishing**: fetch a page's `og:image` URL and read
   the PNG.

       curl -sL -o card.png https://mlghbepw.ogplus.net/observatory-blog/observations/2026-10-03/moon.html

   A real render is 1200 x 628. A blank one is a few kilobytes.
3. **Wait ten minutes after a publish first.** GitHub Pages caches each page
   for 600 s at every edge, OpenGraph+ fetches from a different edge than
   you do, and a render of the old page looks exactly like a bug in the new
   card. This cost three rounds on 4 October 2026.
4. **Dump the cache** when a card has changed and you want to see it now:
   OpenGraph+ keeps a render for at least an hour.

       ogplus cache list <page URL>                      when it was rendered, how big
       ogplus cache rm <page URL>
       echo y | ogplus cache purge bradgessler.github.io  asks y/n; without the echo it fails

   Then fetch each page's card again: a fetch is what draws it. Check all of
   them on a contact sheet, not one.

## Adding a card to a new kind of page

Build the card's HTML in the builder (see `object_card/2`, `collage_card/4`,
`post_card/1`; `card/1` is the box, `beside/2` the words-beside-a-picture
shape), put it in the page as `<template id="ogplus">`, and pass it as
`card:` in the page's share map so the tags follow. Add a test that the
template holds the title, the picture, and no `class=`.
