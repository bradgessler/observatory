defmodule Controller.CenterPointsTest do
  @moduledoc """
  Centered from the pad, in the field with no AI (#94): the press becomes an
  alignment point on whatever the hold is keeping, and says so. With nothing
  held it names nothing.
  """
  use ExUnit.Case, async: false

  alias Controller.Sky.{Lineup, Tracker}

  setup do
    id = "sim-cp-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Telescope.subscribe("center")
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  defp press(id), do: Telescope.broadcast("center", {:centered, %{mount: id, ra: 12.5, dec: -40.0, at: DateTime.to_iso8601(DateTime.utc_now()), by: "pad"}})

  test "with nothing held, it says so and records nothing", %{id: id} do
    press(id)
    assert_receive {:centered_point, ^id, {:unknown, _}}, 2_000
    assert Lineup.samples(id) == []
  end

  test "held, the press is a point on the held target, with the axes from the press", %{id: id} do
    # the hold's readout, as the tracker publishes it while it keeps M13
    :persistent_term.put({Tracker, id}, %{name: "M13", target: %{id: "m13", name: "M13", ra_deg: 250.42, dec_deg: 36.46}})

    press(id)
    assert_receive {:centered_point, ^id, %{name: "M13", n: 1}}, 2_000
    [p] = Lineup.samples(id)
    assert p["name"] == "M13"
    assert p["theta_ra"] == 12.5
    assert p["theta_dec"] == -40.0
  after
    :persistent_term.erase({Tracker, id})
  end
end
