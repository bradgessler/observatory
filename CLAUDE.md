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

**Copy lives in docs.** Explanations go in `priv/docs/*.md` (rendered at
`/docs/:slug`); the UI carries one-line hints and a `?` link.

**Safety in the driver, not the UI.** Held slews self-stop unless refreshed
(`hold: true` + 900 ms deadman). Soft limits are armed by `set_home`. Every
page has STOP. The driver exits and restarts on a lost serial link.

**The mount is the source of truth for position.** No absolute encoders:
power-on = `0x800000` on both axes wherever it is. `Mount.set_home/1` defines
home (counterweight down, tube at the pole). The pointing model
(`Controller.Sky.Pointing`) is first-order and says so; plate solving replaces
it.

**Elixir all the way down.** No side-scripts in the product path. `hack/` is
the one exception: day-one Python probes kept as a record.

## Working here

- `mix test` at the root runs every app. The driver is tested against
  `Mount.Transport.Sim`, which speaks the real wire protocol; LiveViews are
  tested with `Phoenix.LiveViewTest` against a simulated mount.
- Field nights follow `.claude/skills/observing-night`. Findings become issues
  under the current milestone; config-only fixes (axis signs, site) get
  committed.
- Commit messages say what changed and why in plain words, reference issues,
  and end with the session trailer.
- Hardware facts worth remembering: EQ6-R wants 11–16 V centre-positive; the
  HAND CONTROL jack is 3.3 V TTL at 9600 baud; the board ignores axis "3"
  (both) for `F`, `E`, `L` — send per axis.
