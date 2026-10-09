---
name: night-to-website
description: Take a night's frames all the way to the public site — the offload queue onto the Mac Studio, one stacking agent per target, the three versions and the Observations page, the methods post in Brad's voice, previews, a pull request, the merge and the live check. Use when Brad says "stack them", "process the images", "publish it", "write it up" or "write a blog post" after a camera night.
---

# From the card to the website

Done end to end for the night of 8 October 2026 (six targets stacked, five published, one post).
This skill is the order and the hand-offs; the methods are in `stack-pictures`, `finish-pictures`,
`annotate-pictures`, `publish-observations`, `share-cards`, and the voice in the memories
`blog-writing-style` and `blog-location-privacy`.

## 1. Get the frames onto the mothership

The offload queue runs all night, from the first frame (`.claude/skills/mttr/offload.py <night on
the box> ~/.observatory/nights/<date>-a6000/stills <minutes>`): copy, check the SHA-256 against the
sidecar, then remove from the box. Over Wi-Fi from the scope, a shooting Pi 3 serves 80-300 KB/s:
fine for a queue, never wait for Ethernet ("it's never gonna be internet"). A box switched off with
files left keeps them on the card for next time.

Count each target's RAWs against its sidecars by time window before starting its stack (zsh
doesn't split unquoted variables: count in Python).

## 2. One stacking agent per target, in the background

As each target's RAWs land, start an agent with `stack-agent-prompt.md` filled in (target, J2000
position, size, time window, frames and what went wrong with them that night). Deliverables per
target in `~/.observatory/nights/<date>-a6000/<target>/`: `<target>.jpg`, `-1600.jpg` if wide,
`-stack.tif`, `recipe.json`; scripts in `hack/stacks/<date>/<target>/run_all.sh` (bit for bit).
Read each report and look at the picture before sending it to Brad, with a caption that says the
frames kept, why the rest went, and what's real (half-stack checks). Surface the agents' judgement
calls (picture-only sky planes, a flat built from another target's sky, deconvolution kept or not).

Quick JPEG stacks are for a taste mid-night only, labelled as such, registered on stars with
rotation (`quickstack.py` pattern: a pair-offset vote, loose pairs, then a tight RANSAC fit). A
quick look that misaligns gets thrown away, not shown.

## 3. Three versions and the Observations page

One agent, after all the stacks: `annotate-pictures` then `publish-observations` then
`share-cards`. Write `observations/<date>/session.md` yourself first (Brad's voice, only what
happened; he reads it as himself), then let the agent fill `objects.json` and `images/`, build
(`mix site.build`), run `site_build_test.exs`, and preview with
`.claude/skills/publish-observations/tools/preview.sh` (headless Chrome; never the browser pane).
Lead the grid with the strongest picture. Brad decides weak ones (the Crab was cut).

## 4. The methods post

Write it yourself: you have the night's quotes. `posts/<date>-<slug>.md`, front matter like the
others, figures from the night in `posts/images/<date>-*` with metadata stripped (`ffmpeg
-map_metadata -1`), real code from the commits, a "what working with an AI was like" section, and
"what's next". No coordinates, no altitude with a clock time, no RA/Dec on a figure that also says
when; profanity paraphrased, never put softened words in quotes. Link a night as
`../observations/<date>/` (the builder rewrites it).

## 5. Publish

Commit on the branch, merge `main` into it (resolve conflicts keeping both sides; the builder's
tests must stay a superset), push the branch, open a PR (`gh pr create`), bind it (ccd_pr). Pushing
straight to `main` is refused here as a merge without review; Brad says "merge it", then
`gh pr merge`. The blog Action publishes from `main`; check the night's page and the post return
200 before saying they're live:

    https://bradgessler.github.io/observatory-blog/observations/<date>/
    https://bradgessler.github.io/observatory-blog/<date>-<slug>.html
