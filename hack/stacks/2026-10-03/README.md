# The stacks of 3 October 2026

The scripts that turned 990 RAW frames from the Sony a6000 on the 8SE into the
nine pictures at `observations/2026-10-03/`. A record, like the rest of
`hack/`: they are that night's hand work, kept so each picture can be made
again and so the method can be moved into the product. The method itself is
written down in `.claude/skills/stack-pictures`.

| Folder | Picture | Run with |
|---|---|---|
| `ngc7662/` | The Blue Snowball: 25 x 6 s, one field | the `step*.py` in order |
| `m15/` | Messier 15: 23 of 26 x 15 s, one field, flat from its own sky | the `step*.py` in order |
| `m31/` | Andromeda core: 38 of 109 x 20 s through cloud. `step*.py` is the first run (cloud flat); `f*.py` the rerun with the twilight flat | `step1` … `step11`, then `f1` … `f7` |
| `m31-mosaic/` | Andromeda 3 x 2 mosaic joined to the core | `run_all.sh` |
| `m45/` | Pleiades 3 x 3 mosaic | `run_all.sh` |
| `m42/` | Orion Nebula: long and short exposures joined, and the 2 x 2 mosaic round it | `run_all.sh` |
| `moon/` | Last-quarter Moon: lucky imaging over four fields | `run.sh` |
| `saturn/` | Saturn and seven moons: the planet from 1/40 s frames, the moons from 2 s frames | `plan.py` lists the order |

They expect the night's folder at `~/.observatory/nights/2026-10-03-a6000/`
(RAWs in `stills/`, read only), a Python with numpy, scipy, opencv, rawpy,
tifffile and pillow, and astrometry.net on the PATH. Each writes a
`recipe.json` beside its picture with every number it used.

These are not the product. Finishing a stack into a picture is
`.claude/skills/finish-pictures`.

Before this repository is made public: the scripts name frames by their UTC
time. Together with an object and an altitude that places the telescope, so
scrub them first (see the blog's privacy rule in `site.build.ex`).
