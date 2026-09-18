# hack/

Throwaway Python scripts used on day one to prove the EQ6-R talks over the
EQDIR cable, before any Elixir existed. Kept as a record of what the real
mount answered; `Mount.Protocol` and the simulator were written from these.

- `probe.py` — firmware/constants query and a 4 s slow slew (`--slew`)
- `slew_test.py` — 10° forward/back on each axis at goto speed, spoken via `say`
- `axis_tests.py` — sidereal tracking accuracy, speed ladder, stop test, with a ±4° fence

All assume `/dev/cu.usbserial-*` at 9600 baud.
