defmodule Controller.Sky.NeverZeroedTest do
  @moduledoc """
  A mount that was never zeroed: its counts run from wherever it was switched
  on, so an alignment holds until it is switched on again, a Pi reboot or a
  firmware upgrade doesn't count. And with no soft limits, GoTo never lands
  past the meridian.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.{Lineup, Model, Pointing, Tracker}
  alias Controller.Test.KnownMount

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

  # The night of 3 October (#113). The mount stood 60° east of the meridian, counterweight well
  # down, and every plate had been taken near the meridian, the bar within 10° of level. "Most of
  # them had it low" then says nothing, and the guess came out upside down.
  describe "every plate taken with the counterweight bar near level" do
    setup %{id: id} do
      truth = KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])
      %{truth: truth, snap: Mount.snapshot(id)}
    end

    test "the guess is upside down, and Go To would leave the safe pose for the unsafe one", %{id: id, truth: truth, snap: snap} do
      ctx = Pointing.context(DateTime.utc_now(), id)
      assert Lineup.status(id).counterweight == :guessed
      # where the mount stands the counterweight hangs 60° below level; the guess has it 60° above
      assert_in_delta Model.counterweight(truth, truth.signs, snap.axes.ra.degrees), -60.0, 0.5
      assert_in_delta Pointing.counterweight(ctx, snap.axes.ra.degrees), 60.0, 0.5

      plan = Pointing.landing(KnownMount.at_ha(-40.0), snap, ctx)
      assert plan.pose == :flip
      assert Model.counterweight(truth, truth.signs, plan.ra) > 0, "the flip the guess asks for ends with the counterweight in the air"
    end

    test "told it is below level, Go To picks the counterweight-down pose on both sides of the meridian", %{id: id, truth: truth, snap: snap} do
      assert {:ok, _} = Lineup.set_counterweight(id, snap, :below)
      assert Lineup.status(id).counterweight == :told
      ctx = Pointing.context(DateTime.utc_now(), id)

      for ha <- [-40.0, 40.0] do
        plan = Pointing.landing(KnownMount.at_ha(ha), snap, ctx)
        assert plan.cw < 0, "#{ha}° from the meridian: the model lands with the counterweight #{plan.cw}° above level"
        assert Model.counterweight(truth, truth.signs, plan.ra) < 0, "#{ha}° from the meridian: the counterweight really is in the air there"
      end

      # and Go To itself, east of the meridian: it stays in the pose it is in, the safe one
      ref = Enum.find(Mount.list(), &(&1.id == id))
      assert {:ok, d_ra, _d_dec} = Pointing.slew(ref, snap, KnownMount.at_ha(-40.0), ctx, track: false)
      assert Model.counterweight(truth, truth.signs, snap.axes.ra.degrees + d_ra) < 0
    after
      Mount.stop(id)
    end

    # The same wrong guess said the counterweight was above its limit, so the hold refused to
    # start, and with no hold there was no photo with round stars to put the guess right.
    test "a hold starts where the mount stands while the side is a guess, and is refused there only once told", %{id: id, snap: snap} do
      ctx = Pointing.context(DateTime.utc_now(), id)
      assert Pointing.counterweight(ctx, snap.axes.ra.degrees) > Pointing.meridian_hard()

      # that night both axes were run at the model's rates by hand instead, and to Plates
      # every picture taken that way was "moving"
      :ok = Mount.slew(id, :ra, 1.0)
      :ok = Mount.slew(id, :dec, 0.3)
      wait(fn -> Mount.snapshot(id).axes.dec.running end, 3_000)
      assert Controller.Plates.capture(Mount.snapshot(id)).moving
      Mount.stop(id)
      wait(fn -> not Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running end) end, 5_000)

      snap = Mount.snapshot(id)
      {ra, dec} = Pointing.scope_radec(snap, ctx)
      here = %{name: "here", ra_deg: ra, dec_deg: dec}

      # guessed: holding the mount where it already is is not a choice of pose
      Tracker.track(id, here)
      wait(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
      assert Mount.snapshot(id).axes.ra.running
      assert Tracker.ended(id) == nil
      # and a picture taken under the hold belongs to the sky it shows
      refute Controller.Plates.capture(Mount.snapshot(id)).moving
      Tracker.stop(id)

      # told (wrongly, here) that it is above level: now it is known to be past the limit
      assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :above)
      Tracker.track(id, here)
      wait(fn -> match?(%{why: :meridian}, Tracker.ended(id)) end, 6_000)
      assert Tracker.status(id) == nil

      # told what it is, below level: the hold runs
      assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
      Tracker.track(id, here)
      wait(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
      assert Tracker.ended(id) == nil
    after
      Tracker.stop(id)
    end
  end

  # A guess takes the limit away only from where a hold begins. The plates here had the
  # counterweight low, and the mount stands a hair under the limit with the sky carrying it up.
  test "on a guess, a hold that itself carries the counterweight up to the limit still ends there", %{id: id} do
    KnownMount.align(id, Pointing.meridian_hard() - 0.02, [-40.0, -30.0, -20.0, -25.0])
    snap = Mount.snapshot(id)
    ctx = Pointing.context(DateTime.utc_now(), id)
    assert Lineup.status(id).counterweight == :guessed
    assert Pointing.counterweight(ctx, snap.axes.ra.degrees) < Pointing.meridian_hard()

    {ra, dec} = Pointing.scope_radec(snap, ctx)
    Tracker.track(id, %{name: "here", ra_deg: ra, dec_deg: dec})
    # 0.02° of sky is five seconds
    wait(fn -> match?(%{why: :meridian}, Tracker.ended(id)) end, 20_000)
    assert Tracker.status(id) == nil
  after
    Tracker.stop(id)
  end

  # ... and it does not take the limit away for good. If the guess is right, a hold that began
  # past the limit is carrying the tube toward the mount: it turns a short allowance and stops.
  test "on a guess, a hold that begins past the limit turns only a short allowance, and says why", %{id: id} do
    old = Application.get_env(:controller, :guessed_hold_deg)
    # 0.02° of sky is five seconds
    Application.put_env(:controller, :guessed_hold_deg, 0.02)
    on_exit(fn -> if old, do: Application.put_env(:controller, :guessed_hold_deg, old), else: Application.delete_env(:controller, :guessed_hold_deg) end)

    KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])
    snap = Mount.snapshot(id)
    ctx = Pointing.context(DateTime.utc_now(), id)
    assert Lineup.status(id).counterweight == :guessed
    assert Pointing.counterweight(ctx, snap.axes.ra.degrees) > Pointing.meridian_hard()

    {ra, dec} = Pointing.scope_radec(snap, ctx)
    here = %{name: "here", ra_deg: ra, dec_deg: dec}
    Tracker.track(id, here)
    # it starts, as the guess allows
    wait(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
    assert Tracker.ended(id) == nil
    # and ends on its own a little later, both axes stopped
    wait(fn -> match?(%{why: :counterweight}, Tracker.ended(id)) end, 30_000)
    assert Tracker.status(id) == nil
    wait(fn -> not Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running end) end, 5_000)

    # told where it really is, below level, there is no limit to be past: the hold runs on
    assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    Tracker.track(id, here)
    wait(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
    Process.sleep(8_000)
    assert Tracker.ended(id) == nil
    assert Tracker.status(id) != nil
  after
    Tracker.stop(id)
  end

  defp wait(fun, ms) do
    deadline = System.monotonic_time(:millisecond) + ms

    Stream.repeatedly(fn -> Process.sleep(100); fun.() end)
    |> Enum.find(fn ok -> ok or System.monotonic_time(:millisecond) > deadline end)
    |> then(fn ok -> assert ok, "timed out after #{ms} ms" end)
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
