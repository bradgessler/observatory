defmodule Controller.Sky.MoonPhaseTest do
  use ExUnit.Case, async: true

  alias Controller.Sky.Ephemeris

  # 2026's phases: full on Sep 26 (16:49 UTC), new on Oct 10 (15:50 UTC).
  # The first field night the page said "Moon · new" with a nearly full Moon
  # rising in the east: the lit fraction had its sign flipped.
  test "the night before the full Moon is nearly full, and the new Moon is dark" do
    full = Ephemeris.moon_phase(~U[2026-09-26 16:49:00Z])
    assert full.illumination > 0.98
    assert full.name == "full"

    eve = Ephemeris.moon_phase(~U[2026-09-26 02:20:00Z])
    assert eve.illumination > 0.95
    assert eve.waxing

    new = Ephemeris.moon_phase(~U[2026-10-10 15:50:00Z])
    assert new.illumination < 0.02
    assert new.name == "new"
  end

  test "a quarter Moon is about half lit" do
    # first quarter, 2026-10-18 16:12 UTC
    q = Ephemeris.moon_phase(~U[2026-10-18 16:12:00Z])
    assert_in_delta q.illumination, 0.5, 0.08
    assert q.waxing
  end

  test "the Moon's magnitude brightens toward full" do
    assert Ephemeris.position(:moon, ~U[2026-09-26 16:49:00Z]).mag < Ephemeris.position(:moon, ~U[2026-10-03 00:00:00Z]).mag
  end
end
