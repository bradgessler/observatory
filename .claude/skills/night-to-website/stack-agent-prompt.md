# The prompt for one target's stacking agent (fill the <...>)

Stack and finish one target from <date>'s RAW frames, with deterministic methods only. You are working for
Brad Gessler (owner of these observations). Do not publish, push or commit anything; do not touch any
box/telescope (no ssh, no curl to the box); do not use the app's browser pane.

TARGET: <name, catalogue id>, <kind, size>, J2000 RA <deg>, Dec <deg>. <Anything about it: fills the frame
(no sky surface over it, one constant per colour per frame at most), faint (prove it with half stacks or say
it isn't there), low behind an obstruction, bright core (don't clip)...>

FRAMES: Sony a6000 RAW + JPEG + sidecar .json in ~/.observatory/nights/<date>-a6000/stills/ (READ ONLY).
This target's frames have time stamps (characters 10-15 of the name) from <hhmmss> to <hhmmss>: <n> frames,
<exposure> at ISO <iso>, Celestron 8SE (~2,082 mm by plate solve, f/10), EQ-6R on a pointing model. <What went
wrong that night: centring frames, frames smeared while the hold settled (select by star size <= ~6.5",
elongation <= 1.35, common-direction ellipticity <= 0.2, none within 10 s of a move), cloud between hh:mm and
hh:mm, frames of another target in the window...>. <Darks/flats or none.>

METHOD: read and follow .claude/skills/stack-pictures/SKILL.md (including "What the night of 8 October 2026
added") and .claude/skills/finish-pictures/SKILL.md. Templates: hack/stacks/2026-10-08/m57/ and
hack/stacks/2026-10-08/ngc1514/. RAW planes, hot pixels from the run, star registration with rotation,
dispersion out in the one resampling, transparency weights, sigma-clipped weighted mean, one sky constant per
colour per frame in the stack (picture-only sky planes far from the object allowed, stated). Finish: neutral
black, quiet sky over faint extra detail, gentle deterministic stretch, never enlarge, plate solve to confirm
(solve-field at /opt/homebrew/bin/solve-field, index files under ~/.observatory/astrometry). NO neural/AI
denoise, sharpen or upscaling. Deconvolution only with a measured blur, gain-capped, as a labelled extra.

TOOLS: ~/.observatory/pyenv/bin/python (numpy, scipy, opencv, rawpy, tifffile, pillow). Scripts in
hack/stacks/<date>/<target>/ (numbered + run_all.sh, reproducible bit for bit). Work in
~/.observatory/nights/<date>-a6000/<target>/work/ and delete big intermediates; other agents run at the same
time, keep memory and disk modest.

DELIVER to ~/.observatory/nights/<date>-a6000/<target>/: <target>-stack.tif (16-bit linear), <target>.jpg
(native scale), <target>-1600.jpg if wider, <target>-single-vs-stack.jpg, recipe.json. No metadata in the
JPEGs. Report: frames used/dropped and why, star size, noise vs one frame, what it shows and what is proven
real, judgement calls for Brad, problems, paths.
