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

  # The night every photo was taken with the counterweight bar near level: the guess said the
  # counterweight would rise going west, the mount's own photo said it falls. Told, it holds.
  test "the counterweight's side can be told, and what is told outlives new photos", %{id: id} do
    now = DateTime.utc_now()
    pts = [point("a", 279.23, 38.78, 10.0, 40.0, now), point("b", 297.70, 8.87, 30.0, 70.0, now), point("c", 310.36, 45.28, 20.0, 30.0, now)]
    Lineup.replace(id, pts, nil)
    m = Lineup.model(id)
    assert Lineup.status(id).counterweight == :guessed

    snap = Mount.snapshot(id)
    h = m.signs.ha_sign * snap.axes.ra.degrees + m.off_ra
    level = :math.asin(:math.sin(h * :math.pi() / 180)) * 180 / :math.pi()

    if abs(level) < 10 do
      # the bar is level: lower or higher cannot be seen, the side can
      assert Lineup.set_counterweight(id, snap, :below) == {:error, :level}
      {:ok, east} = Lineup.set_counterweight(id, snap, :east)
      {:ok, west} = Lineup.set_counterweight(id, snap, :west)
      assert east == -west
    else
      {:ok, below} = Lineup.set_counterweight(id, snap, :below)
      # told below: the model's counterweight is below level here
      assert Controller.Sky.Model.counterweight(Lineup.model(id), m.signs, snap.axes.ra.degrees) < 0
      {:ok, above} = Lineup.set_counterweight(id, snap, :above)
      assert above == -below
      assert Controller.Sky.Model.counterweight(Lineup.model(id), m.signs, snap.axes.ra.degrees) > 0
    end

    told = Lineup.model(id).cw
    assert Lineup.status(id).counterweight == :told

    # more photos, whatever they would have guessed: the told side stays
    Lineup.replace(id, pts ++ [point("d", 250.0, 20.0, -60.0, 50.0, now), point("e", 240.0, 10.0, -70.0, 60.0, now)], nil)
    assert Lineup.model(id).cw == told
    assert Lineup.status(id).counterweight == :told

    # and it can be handed back to the guess
    assert Lineup.set_counterweight(id, snap, :guess) == {:ok, nil}
    assert Lineup.status(id).counterweight == :guessed
  end

  test "with no alignment there is nothing to hang the counterweight on", %{id: id} do
    assert Lineup.set_counterweight(id, Mount.snapshot(id), :below) == {:error, :not_lined_up}
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
