# Observatory — how we build it

Telescope control in Elixir: a mount driver, a Phoenix LiveView controller, a
Nerves image for a Pi. Casual on top ("plug in, look at stuff"), precise
underneath; one system, progressive disclosure. Plans live in GitHub issues
and the project board, not here.

## Shape

```
apps/telescope   PubSub + cluster membership (Telescope.subscribe/broadcast)
apps/mount       EQ6-R driver: Mount.Protocol, Mount.Transport.{Serial,Sim}, Mount.Server, Mount.Discovery
apps/controller  Phoenix LiveView UI: keypad, sky, object, setup, devices, docs
firmware/        Nerves poncho project pulling apps/mount + apps/telescope
```

`mix phx.server` at the root runs everything on the laptop; the mount appears
when the EQDIR cable is plugged in, a simulator runs when it isn't.

## Rules

**Server-driven state, always.** The mount's state lives in `Mount.Server`,
which broadcasts a snapshot on `"mount:<id>"` every 250 ms and on every change.
Every LiveView subscribes and renders from assigns. Multiple phones and the
laptop see the same telescope at the same time; nothing about the telescope is
ever held only in a browser. Per-viewer things (which tab, a picked object) are
plain assigns. Persisted settings go through `Controller.Settings`, which
broadcasts on `"settings"`; pages subscribe so a change on one phone shows on
all of them.

**LiveView, not JavaScript.** Pages are HEEx. `priv/static/assets/js/app.js`
is the whole JS budget and every hook in it has a written reason at the top of
the file (gestures and browser-only APIs: touch-and-pull, pinch-zoom, reading
photo pixels, geolocation). Before adding JS, ask whether LiveView already
does it (`phx-window-keydown`, `phx-click`, streams) or the server can render
it. No bundler: LiveView's JS is served from deps.

**Components, one grid, true black.** Build screens from
`Controller.Components.UI` and follow `apps/controller/DESIGN.md`: 8-px
spacing, one radius, black ground for OLED, red night mode, no tap flash, no
expansion panels (secondary things get a page and a back link).

**Modes are loud.** Anything persistent that changes where the scope goes
(sync offset, flipped axis sign, reversed tracking, auto-track off, site
override) is reported by `Controller.Modes.active/0` and shown on every page.

**Knobs live in functions; the UI shows what tonight needs.** Every
configurable thing is a parameter on a public function (`Video.start(quality:,
fps:)`, `Mount.slew(ref, axis, rate, hold:)`) so it can be driven from a page,
an agent or IEx later. The UI right now is for three jobs — drive the scope,
make setup quick, say how locked-on tracking is — and shows only what those
need. A knob the machine can decide (video size, encoder, ports to try) is
decided by the machine, with an override on a secondary page. Deep-science
and deep-astro surfaces come later, on their own pages, without changing the
functions underneath.

**Ask the browser only when needed; assume it will say no.** Location, the
orientation sensor, the camera: request them from a tap, at the moment a
feature needs them, never on page load. Whatever the answer, the page keeps
working — a manual field (lat/lon typed in), a different control surface
(keypad instead of tilt), a still instead of video — and one calm line says
which it is using and how to change it. Never a banner that nags a laptop
about location it cannot have.

**Copy lives in docs.** Explanations go in `priv/docs/*.md` (rendered at
`/docs/:slug`); the UI carries one-line hints and a `?` link.

**WCAG 2.1 AA is the floor, in every theme.** It is good design and it is
how you read a phone at an eyepiece. Concretely: text 4.5:1 against the
surface it sits on and 3:1 for a key's edge and for any lit state
(`test/controller/design_test.exs` computes this from `tokens.css` and
fails the build otherwise); every control at least 44 px tall; a visible
focus ring; state carried by words or a mark as well as a tone (a lit key
also changes its text; a done step also gets a ✓); roles and states in the
markup (`radiogroup`/`radio` with `aria-checked`, `aria-current="step"`,
`role="status"` on notices, an `aria-label` on every icon-only key); no
motion that cannot be turned off. Show, don't tell: state is drawn (a
greyed key, a lit key, a dot on a target), words are for what a picture
can't say, and a list row is two lines, the name over its detail, never
crammed onto one. One type scale: 12, 14, 16, 20, 28 px. No em dashes in
the UI, no red except STOP and a real warning.

**Safety in the driver, not the UI.** Held slews self-stop unless refreshed
(`hold: true` + 900 ms deadman). Soft limits are armed by `set_home`. Every
page has STOP. The driver exits and restarts on a lost serial link, and stops
both axes on every (re)connect and in `terminate/2`, so a restart can never
inherit motion.

**Every crash is a gap in the supervision tree.** Flaky cables, cameras that
stop delivering frames, encoders that hang, a pad unplugged mid-slew: reality
will try to take the stack down all night. Each piece of hardware and each
workload is its own process under its own supervisor with restart limits,
and a failure there is *contained*: the mount keeps working when the camera
dies, the stills keep coming when the encoder dies, and the page says what
is down in one calm line. When something crashes, the fix is never just the
bug — it is also the missing boundary that let one failure become two, and
the missing "keeps crashing, giving up" step (restart budget, then a clear
message and a manual path).

**Only fresh intent moves the scope.** (From the night the pad kept the mount
moving after the hand let go: a mapper fell behind and replayed a mailbox of
stale "trigger held" reports, each one re-feeding the deadman.) Every input
path — pad, stick, keyboard, future voice — must: stamp each report with
monotonic time and drop anything older than ~250 ms; coalesce backlogs to the
newest report; run its own watchdog that releases when input goes quiet;
bound every call into the driver; start disarmed and disarm itself on any
error. A deadman that is fed by stale commands is not a deadman. Remember that
BEAM monotonic time is negative: never compare against 0.

**The mount is the source of truth for position.** No absolute encoders:
power-on = `0x800000` on both axes wherever it is. `Mount.set_home/1` defines
home (counterweight down, tube at the pole). The pointing model
(`Controller.Sky.Pointing`) is first-order and says so; plate solving replaces
it.

**Elixir all the way down.** No side-scripts in the product path. `hack/` is
the one exception: day-one Python probes kept as a record.

**Hardware is read by the server, never the browser.** Serial goes through
`circuits_uart`; USB HID (game controllers) goes through `apps/input`, a
GenServer per device over a tiny C port program linked to libhidapi
(`apps/input/c_src/hidport.c`), which builds the same on macOS and Linux. The
UI shows device state and never depends on a browser's device APIs, so
everything works in Safari, Firefox, a phone — web standards only, no
Chrome-only paths.

**When state needs a store, it's Ecto + SQLite with migrations from day one**
(hardware registrations, sites, sessions). Not yet: `~/.observatory/settings.json`
is enough while we're playing. The moment a second table appears, add the
Repo and migrate the settings into it.

## Working here

- `mix test` at the root runs every app. The driver is tested against
  `Mount.Transport.Sim`, which speaks the real wire protocol; LiveViews are
  tested with `Phoenix.LiveViewTest` against a simulated mount.
- Field nights follow `.claude/skills/observing-night`. Findings become issues
  under the current milestone; config-only fixes (axis signs, site) get
  committed.
- Commit messages say what changed and why in plain words, reference issues,
  and end with the session trailer.
- When an epic or milestone closes, write it up: a concise post in `posts/`
  in Brad's voice (read a few pieces on bradgessler.com first), with
  screenshots of what was built, real code snippets (it's open source), what
  went wrong on the way, and what's next. Progress people can read is how
  others get inspired to run and hack on this.
- Hardware facts worth remembering: EQ6-R wants 11–16 V centre-positive; the
  HAND CONTROL jack is 3.3 V TTL at 9600 baud; the board ignores axis "3"
  (both) for `F`, `E`, `L` — send per axis.
