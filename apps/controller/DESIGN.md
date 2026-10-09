# Controller UI — design system

One visual system for every screen (keypad, sky, targets, guest page). The UI is
a product, not a debug panel. It is used outdoors, at night, one-handed, by
people who may have never used a telescope.

## Ground rules

- **True black, tones for structure.** `--bg` is `#000`: on an OLED phone the
  ground is off. Surfaces are told apart by tone (`--panel`, `--panel2`,
  `--sunk`), never by hairlines. No borders anywhere.
- **Keys, not buttons.** Anything you can push is a key: a surface one step
  lighter than the panel with a soft edge (`--key-edge`) and a little lift
  (`--bevel`); pressed, it goes flat and dark. A latched state is a lit key
  (`--lit`, `--lit-on`, `--lit-warn`) with a faint accent edge, not an
  outline. Fields and troughs are sunk (`--bevel-in`). Calm and modern, and
  still plainly something to push.
- **One grid.** Spacing steps of 8 (`--s1` 8, `--s2` 12, `--s3` 16, `--s4` 24);
  one corner radius (`--r` 14, cards 16); page width 560 centred; every page
  opens with the same toolbar (below), so its title sits in the same place.
- **Components, not markup.** Pages are built from `Controller.Components.UI`
  (`page`, `back`, `title`, `actions`, `help`, `card`, `row`, `kv`, `setting`,
  `badge`, `hint`, `btn`) and `Controller.Components.Modes`. A new screen
  should need no new CSS for layout.
- **No expansion.** Secondary controls get their own page and a back link,
  never a disclosure that reflows the screen.
- **Modes are loud.** Anything persistent that changes where the scope goes
  (sync offset, flipped axis, reversed tracking, auto-track off, site override)
  shows as an amber strip on every page while it's on, linking to Setup.
- **No bar down the left edge.** A picked, current or live thing is never
  marked with a coloured stripe on its left side, least of all on a rounded
  shape. It gets a lit fill, its own key or badge filled solid, and a mark
  that means something there (a chevron at the panel it opened, a ✓); legends
  colour their glyph.
- **One affordance per thing.** A tile is the tile; no second button beside it.
  Docs are reached from the destination page's `?`, never from a list.

## Accessible by default (WCAG 2.1 AA)

- **Contrast is tested, not guessed.** `priv/static/assets/css/tokens.css`
  is the whole palette, three themes, and `test/controller/design_test.exs`
  asserts 4.5:1 for every ink on every surface. A key is identified by its
  label, so its edge is soft on purpose (a lighter surface, a faint edge, a
  little lift; flat when pressed; a faint accent edge when lit). Change a
  colour there or nowhere.
- **Targets ≥ 44 px, focus visible, no colour alone.** A lit key also
  changes its text; a done step also gets a ✓; a notice is `role="status"`;
  segmented controls are `radiogroup`/`radio` with `aria-checked`; the flow
  strip marks `aria-current="step"`; icon-only keys carry an `aria-label`.
- **One type scale.** `--fs-1` 12 (labels, badges), `--fs-2` 14 (secondary,
  hints), `--fs-3` 16 (body, keys, fields), `--fs-4` 20 (the one strong line
  on a card), `--fs-5` 28 (axis readouts). Nothing else.
- **Rows are two lines.** A list row is the name, then its detail under it,
  then the keys; never a bold word with small text crammed after it.
- **Every page, by keyboard and by screen reader.** A skip link to `#content`
  (rendered once per document by `page`), one `<main>` and one `h1` per
  document, a distinct `page_title` per LiveView, arrow keys drive the plain
  keypad, the orb strips and the tilt pad (auto-repeat feeds the dead-man;
  keyup releases) and Escape stops, `UI.rates` is a radiogroup, `UI.items`
  is a list, `UI.lamp` says "moving"/"still" in words, toggles carry
  `aria-pressed`, the current tab or step `aria-current`, destructive keys a
  confirm. `pages_test.exs` "accessibility" checks these on every route.

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
| `--bg`, `--panel`, `--panel2`, `--sunk` | page, cards, a step up inside a card, troughs and fields |
| `--key`, `--key-press`, `--bevel`, `--bevel-in` | a pushable key, the same key pressed |
| `--lit`, `--lit-on`, `--lit-warn` | a latched key: current choice, active/good, a state to notice |
| `--hi`, `--lo` | the two bevel edges |
| `--text`, `--dim` | primary text, secondary/labels |
| `--accent` | the current selection (rate, tab) |
| `--on` | active state: tracking, home set, picked, "go" |
| `--warn` | STOP and the scope marker only |
| `--sky1`, `--sky2` | sky dome gradient |

Type: system UI font, 16px base, tabular numerals for anything that changes.
Radii: 14px controls, 16px cards, 999px pills. Spacing: 8/10/12/14/16.

## The toolbar

Every page's header is `back` · `title` · `actions`, drawn by `UI.back/1`,
`UI.title/1` and `UI.actions/1`; the docs pages draw the same markup by hand.

- **Left-aligned, fixed height, sticky.** The leading key, an overline over
  the title, the keys on the right. The title never centres, so it never moves
  when the keys change; the bar stays at the top while the page scrolls, so
  STOP is always in reach.
- **The leading key says where it goes.** On a sidebar page it is Home (a
  house), and the overline is the page's sidebar section ("Controls"), with the
  mount it acts on after a dot in its own spelling ("Controls · ttyUSB0"). On a
  page under another it is a back chevron, and the overline is that page's name.
  On a wide screen the sidebar is home, so the house goes.
- **Getting around, help, STOP. Nothing else.** The keys are Search (the
  sidebar has it on a wide screen), the page's `?`, night mode where it's
  needed at the eyepiece, and STOP, always last. An action on the page's
  content (Scan, Connect) goes on the page, beside what it acts on.
- **Small screens keep every key at 44 px.** Under 600 px the title is a size
  down; under 360 px the overline drops its capitals and a long title takes a
  second line rather than losing its end.
- **A section's status rides in the toolbar and never widens it.**
  `UI.status/1` (the Sky's time and place, what the mount is doing, how well
  it's aligned) sits beside the title where its one line fits, and takes its
  own row under the title where it doesn't: always on a phone. It takes its
  width from the toolbar, never from what's in it, so what's in it wraps to
  a second line or ends in an ellipsis, and a toolbar never scrolls
  sideways. The Sky's status on a phone is two lines that hold still: the
  time stepper across the first, how dark it is and the place on the second
  (its solar graph makes way under 540 px). A page wider than the phone
  makes the phone zoom the whole page out; `design_test.exs` checks the
  stylesheet for it.

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
- State is shown, not implied: running dots on the axes, `tracking`/`home set`
  badges, the picked object ringed on the map, the scope marker.
- One primary action per panel (`.go`), secondaries plain.

## Casing

One rule, everywhere: **Title Case** for page titles, card titles, nav and
tab labels and every key label ("Set Home Here", "Track What I'm On");
**sentence case** for every sentence, subtitle, hint, state line and notice
(a capital first letter, the rest as written); badges stay small uppercase.
Nothing on a page starts with a lowercase letter. Dynamic fragments go
through `UI.sentence/1` when they open a line.

## Copy

- One word per thing, the one in `priv/docs/glossary.md` ("Words", at
  `/docs/glossary`): home position, Go To, tracking, alignment, plate solve,
  frame. A new term goes there first, with a link to where it is explained.
- Call things what they are. The person using this sets up their own
  network gear; write for them. Hostname, SSID, access point, password, SD
  card, board, SSH: the standard term, never a friendly paraphrase ("Its
  Name", "The Door", "Eyes"). A paraphrase makes someone translate it back to
  the real term before they can act on it.
- Show the value, not a description of it. A field starts filled in with the
  default the machine will really use; a blank field never secretly means
  something. Beside a setting goes its concrete result ("observatory.local"),
  not reassurance.
- Plain words only where the plain word is the precise one: "set home" not
  "park" (the mount has no park position); magnitudes translated for the
  current equipment.
- Tell people what to do next when something is missing: "set home first",
  "no mount found, plug the cable into this machine".
- Honest labels for approximations: the pointing model says it is unverified.

## Layers (fractal complexity)

Casual controls sit on top; every layer beneath exposes the same functions
with more parameters. Add advanced controls behind a tab or a long-press, not
as a second app. Guest/star-party views are *restricted parameterizations* of
the same LiveViews.
