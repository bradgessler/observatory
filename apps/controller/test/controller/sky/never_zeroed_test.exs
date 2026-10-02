defmodule Controller.Sky.NeverZeroedTest do
  @moduledoc """
  A mount that was never zeroed: its counts run from wherever it was switched
  on, so an alignment holds until it is switched on again, a Pi reboot or a
  firmware upgrade doesn't count. And with no soft limits, GoTo never lands
  past the meridian.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.Lineup

  setup do
    id = "sim-nz-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  defp point(name, ra, dec, tr, td, at),
    do: %{"name" => name, "at" => DateTime.to_iso8601(at), "theta_ra" => tr, "theta_dec" => td, "ra_deg" => ra, "dec_deg" => dec}

  test "a never-zeroed alignment holds, until the mount is switched on after it", %{id: id} do
    now = DateTime.utc_now()
    Lineup.replace(id, [point("Vega", 279.23, 38.78, 10.0, 40.0, now), point("Altair", 297.70, 8.87, 30.0, 70.0, now)], nil)
    refute Mount.snapshot(id).homed
    refute Lineup.stale?(id)
    assert Lineup.model(id)

    # the mount is switched on again: the counts restarted, the stars no longer hold
    Controller.Settings.put("mount_power_on", Map.put(Controller.Settings.get("mount_power_on", %{}), id, System.os_time(:millisecond) + 1_000))
    assert Lineup.stale?(id)
    refute Lineup.model(id)
  after
    Controller.Settings.put("mount_power_on", Map.delete(Controller.Settings.get("mount_power_on", %{}), id))
  end

  test "Centered asks first, records the point on a yes, and can be undone", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/object/m13?mount=#{id}")
    html = render_click(view, "sync", %{})
    assert html =~ "in the middle of the eyepiece?"
    assert Lineup.samples(id) == []

    html = render_click(view, "sync_confirm", %{})
    assert html =~ "Centered on"
    assert length(Lineup.samples(id)) == 1
    assert html =~ "Undo That Centered"

    html = render_click(view, "undo", %{})
    assert html =~ "Took back the last Centered"
    assert Lineup.samples(id) == []
  end

  test "a wrong tap is cancelled with nothing recorded", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/object/m13?mount=#{id}")
    render_click(view, "sync", %{})
    html = render_click(view, "sync_cancel", %{})
    refute html =~ "in the middle of the eyepiece?"
    assert Lineup.samples(id) == []
  end
end
