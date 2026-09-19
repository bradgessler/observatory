# Controller UI — design system

One visual system for every screen (keypad, sky, targets, guest page). The UI is
a product, not a debug panel. It is used outdoors, at night, one-handed, by
people who may have never used a telescope.

## Ground rules

- **True black.** `--bg` is `#000`: on an OLED phone the ground is off, panels
  are barely lifted (`#0a0c11`), hairlines are the only structure. Calm.
- **One grid.** Spacing steps of 8 (`--s1` 8, `--s2` 12, `--s3` 16, `--s4` 24);
  one corner radius (`--r` 14, cards 16); page width 560 centred; headers are a
  three-column grid (back · title · actions) so every page's title sits in the
  same place.
- **Components, not markup.** Pages are built from `Controller.Components.UI`
  (`page`, `back`, `title`, `actions`, `help`, `card`, `row`, `kv`, `setting`,
  `badge`, `hint`, `btn`) and `Controller.Components.Modes`. A new screen
  should need no new CSS for layout.
- **No expansion.** Secondary controls get their own page and a back link,
  never a disclosure that reflows the screen.
- **Modes are loud.** Anything persistent that changes where the scope goes
  (sync offset, flipped axis, reversed tracking, auto-track off, site override)
  shows as an amber strip on every page while it's on, linking to Setup.

## Night vision first

- **Two palettes, one toggle (◐), remembered.** `default` is a dim dark-sky
  palette; `night` is red-only. Both are CSS custom properties on `:root` /
  `.night`, so a component never hard-codes a colour.
- **Night mode is red on black, nothing else.** No white, no blue, no green;
  even "on" and "warning" states are shades of red. Star dots become red.
  Peak brightness in night mode stays under `#ff4a4a`-on-`#050000`.
- **Never flash.** No white splash, no bright transitions, no full-screen
  notices. Notices are a quiet grey line at the bottom that fades on its own; never red, never a fill.
- **Dim by default.** Text is `--text` on `--bg` at ~85% contrast, not pure white
  on black. Large numbers (position readout) are the brightest thing on screen.

## Tokens (`priv/static/assets/css/app.css`)

| token | role |
|---|---|
| `--bg`, `--panel`, `--edge` | page, cards, hairlines |
| `--text`, `--dim` | primary text, secondary/labels |
| `--accent` | the current selection (rate, tab) |
| `--on` | active state: tracking, homed, picked, "go" |
| `--warn` | STOP and the scope marker only |
| `--btn`, `--btn-press` | button fill, pressed fill |
| `--sky1`, `--sky2` | sky dome gradient |

Type: system UI font, 16px base, tabular numerals for anything that changes.
Radii: 14px controls, 16px cards, 999px pills. Spacing: 8/10/12/14/16.

## Every screen size

Phone first, but the same pages run on an iPad, a laptop, and a 5K desktop.
- Phone (< 700px): single column, thumb reach, tabs switch panels.
- Tablet/laptop (≥ 960px): the sky page becomes two columns — map left,
  tabs/list/pick right — so list ↔ map correspondence is visible at once.
- Big desktop (≥ 1800px): base font scales up; nothing becomes tiny.
- Touch and pointer both: controls are `touch-action: manipulation` and
  `user-select: none`; hover styles only under `@media (hover: hover)`; no
  behaviour depends on hover. Pointer events (not mouse/touch events) drive
  press-and-hold.

## Touch and motion

- Every control ≥ 44px; the D-pad and STOP are much bigger. STOP is always
  the most visible control on the keypad; EMERGENCY STOP is full-width red.
- Press-and-hold is real (pointer events + a server deadman), never a toggle.
- State is shown, not implied: running dots on the axes, `tracking`/`homed`
  badges, the picked object ringed on the map, the scope marker.
- One primary action per panel (`.go`), secondaries plain.

## Copy

- Plain words over jargon. "Set home" not "park"; "tree line" not "horizon
  mask"; magnitudes always translated for the current equipment.
- Tell people what to do next when something is missing: "set home first",
  "no mount found, plug the cable into this machine".
- Honest labels for approximations: the pointing model says it is unverified.

## Layers (fractal complexity)

Casual controls sit on top; every layer beneath exposes the same functions
with more parameters. Add advanced controls behind a tab or a long-press, not
as a second app. Guest/star-party views are *restricted parameterizations* of
the same LiveViews.
