---
name: annotate-pictures
description: Make the three versions of every finished astronomy picture that the user shares — plain, annotated with names and the facts that blow people's minds (what it is, how far, how big, when the light left), and "how it was made" for photographers (frames, exposures, mosaic fields outlined, calibration). Use when the user asks to annotate, label, caption, add facts or scale, make shareable versions, or explain how a picture was put together.
---

# Three versions of every picture

    <name>.jpg             the picture, nothing on it
    <name>-annotated.jpg   names, a scale bar and north on the picture; underneath: what it is, four facts, the credit
    <name>-how.jpg         for photographers: the fields that were joined, outlined; underneath: twelve rows of how

Full size, JPEG quality 93, no chroma subsampling, no metadata. The caption
goes in a band under the picture and never covers it. `tools/annotate.py`
does all three; it is written per night: copy it into the night's folder
beside `final/` and rewrite its `targets()` table.

## The user's rules

- **Sentence case.** Titles, labels, facts, everything. No all-capitals labels,
  no Title Case. ("Sentence case annotations.")
- **Never enlarge.** No blown-up inset of a small subject. ("Don't enlarge
  Saturn.") A crop at the picture's own pixels is fine.
- **Their name on it.** The credit line leads with "© 2026 Brad Gessler".
- **Mind-blowing, and true.** For a deep-sky object: what it is, the
  distance, what the picture spans, when the light left. Say it for someone
  who has never looked through a telescope.
- **Nothing that places the telescope.** "San Francisco Bay Area", never the
  town. And never an altitude with a clock time: with the object's name that
  is a position line. Give the altitude and the part of the night ("before
  dawn"), not UTC.
- Words are plain: no em dashes, no jargon in the annotated version. The
  photographers' version is where the jargon goes.

## The facts

Work each one out and keep the arithmetic in the table:

- the picture spans = distance x its angular width (arcmin x 2.909e-4);
- the light left = this year minus the distance in light-years, then find
  what was happening then (Orion: the year 680; the Pleiades: 1582, the year
  the calendar changed; Andromeda: stone tools);
- one pixel = distance x arcsec per pixel x 4.848e-6;
- the scale bar is a round physical length, with its angle underneath.

Say when a number is soft ("roughly 5,700 light-years, not well known") and
when a picture has a flaw ("taken before the telescope was refocused, so it
is soft"; "the glow round Atlas is thin cloud, not nebula"). An honest note
is one of the four facts when there is something to be honest about.

## The labels

A label goes on a thing you have found in the picture, not on where a
catalogue says it should be.

- Put positions through the picture's own geometry: the level-and-crop map
  from `level.py` (`source_px_to_this_px`), the plate solution, or for the
  Moon the orthographic projection with that night's libration
  (`moon_place`). Then let `peak()` find the bright thing nearby.
- **Look at a full-size crop of every label** before believing it. That
  check found: labels drawn with another picture's map (a variable reused
  between two targets), Plato in shadow past the terminator (replaced by
  Montes Recti), a leader ending above the dust lane it named.
- A feature in shadow gets no label. A name that is an inference says so
  (Saturn's inner moons, named from how they moved).
- Mark the thing people will mistake: the bright field star beside Saturn
  is labelled "A star, not a moon".
- Leaders stop short of the object; text sits on a dark pill so it reads
  over bright ground; nothing overlaps.

## How it was made

The same picture with each sensor frame of a mosaic outlined and named
"panel: kept of taken" (`footprints()` lays them out from the panel offsets
and the frame's axes on the sky), a scale bar in arcminutes with the
sampling under it, and rows for: exposures, frames taken and kept and why
the rest were lost, mosaic or high dynamic range method, sampling, field,
when and how high (no clock time), calibration, stacking, finish, telescope,
camera, mount. Copy the numbers from each stack's `recipe.json`, not from
memory. When two exposures make one picture (Saturn), label which part came
from which.

## Running it

    python annotate.py [name ...]        the share set, into share/
    python annotate.py --site <repo>/observations/<date>
                                         the same pictures and words for the website: images/ and objects.json

Look at every output. Then `publish-observations`.
