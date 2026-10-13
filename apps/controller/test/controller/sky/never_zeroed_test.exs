defmodule Controller.Sky.NeverZeroedTest do
  @moduledoc """
  A mount that was never zeroed: its counts run from wherever it was switched
  on, so an alignment holds until it is switched on again, a Pi reboot or a
  firmware upgrade doesn't count. And with no soft limits, GoTo never lands
  past the meridian. Which side the counterweight is on no alignment can see:
  until someone says, nothing moves by the guess (#113).
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
    # an alignment here can correct the global axis signs: put them back, or the modules that
    # run after this one solve their photos under a flipped Dec
    pointing = Controller.Settings.get("pointing")

    on_exit(fn ->
      Lineup.clear(id)
      Controller.Settings.put("pointing", pointing)
    end)

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

  # 12 October 2026: the side told on the 8th was still with the alignment four nights later,
  # after the tripod had been carried in and out. A mount switched off and on while the box is
  # off shows no sign of it once it has been moved, so nothing here can know. What it can know
  # is that the answer is old.
  test "a side told another night is not carried into a new alignment: it is asked again", %{id: id} do
    KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])
    assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    assert Lineup.status(id).counterweight == :told
    samples = Controller.Settings.get("lineup")[id]["samples"]

    # the same night: a new alignment keeps what was told
    Lineup.replace(id, samples, nil)
    assert Lineup.status(id).counterweight == :told

    # thirteen hours on: a new alignment starts from a guess
    all = Controller.Settings.get("lineup")
    old = DateTime.utc_now() |> DateTime.add(-13 * 3600, :second) |> DateTime.to_iso8601()
    Controller.Settings.put("lineup", put_in(all, [id, "at"], old))
    Lineup.replace(id, samples, nil)
    assert Lineup.status(id).counterweight == :guessed
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

    # The same guess again on 8 October: a Go To from Tonight's List drove the tube to the pose
    # with the counterweight bar 64° above level, the camera near a tripod leg. So on a guess
    # nothing moves by it: not a Go To, not either leg of a flip, until someone says.
    test "while the side is a guess, Go To and the flip's first leg refuse, and nothing moves", %{id: id, snap: snap} do
      ref = Enum.find(Mount.list(), &(&1.id == id))
      ctx = Pointing.context(DateTime.utc_now(), id)
      assert Pointing.side_guessed?(snap, ctx)

      for ha <- [-40.0, 40.0] do
        assert Pointing.slew(ref, snap, KnownMount.at_ha(ha), ctx, track: true) == {:error, :counterweight_unknown}
        # the same with "stay this side, I'm watching" and with the flip's second leg
        assert Pointing.slew(ref, snap, KnownMount.at_ha(ha), ctx, watched: true) == {:error, :counterweight_unknown}
        assert Pointing.slew(ref, snap, KnownMount.at_ha(ha), ctx, flip: true) == {:error, :counterweight_unknown}
      end

      # the first leg goes to where the model has the counterweight straight down: on a guess, straight up
      assert Pointing.home_leg(ref, snap, ctx) == {:error, :counterweight_unknown}
      assert Controller.Sky.Moves.flip(id, KnownMount.at_ha(40.0)) == {:error, :counterweight_unknown}
      assert Controller.Sky.Moves.pending(id) == nil

      # nothing was sent: both axes where they were, still, and nothing held
      Process.sleep(500)
      now = Mount.snapshot(id)
      refute Enum.any?(now.axes, fn {_, ax} -> ax.running or Map.get(ax, :goto_pending, false) end)
      assert now.axes.ra.degrees == snap.axes.ra.degrees
      assert now.axes.dec.degrees == snap.axes.dec.degrees
      refute Tracker.active?(id)

      # the words a page shows: the one question someone at the mount can answer by looking
      assert Pointing.refusal_words(:counterweight_unknown, "M31") =~ "Which side is the counterweight on?"
      assert Pointing.refusal_words(:counterweight_unknown, "M31") =~ "below or above level right now"
    end

    test "told it is below level, Go To picks the counterweight-down pose on both sides of the meridian", %{id: id, truth: truth, snap: snap} do
      assert {:ok, _} = Lineup.set_counterweight(id, snap, :below)
      assert Lineup.status(id).counterweight == :told
      ctx = Pointing.context(DateTime.utc_now(), id)
      refute Pointing.side_guessed?(snap, ctx)

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

    # 12 October: indoors, asked below or above for a Go To, with nobody at the mount to look. A
    # key tapped at random is a guess recorded as a fact. "I don't know" is an answer: the mount
    # goes on moving, only through turns of the RA axis it has already stood at, which are as
    # safe as they were whichever side is the truth.
    test "I don't know is an answer: Go To goes where the RA axis has stood and no further, whichever side is true", %{id: id, truth: truth, snap: snap} do
      assert Lineup.set_counterweight(id, snap, :unknown) == {:ok, :unknown}
      assert Lineup.status(id).counterweight == :unknown
      ctx = Pointing.context(DateTime.utc_now(), id)
      refute Pointing.side_guessed?(snap, ctx)
      assert Pointing.side_unknown?(snap, ctx)

      # it stands 60° from level and its plates were taken 2° to 8° the other way: that range, and a little
      {lo, hi} = Pointing.unknown_range(ctx)
      assert_in_delta lo, -65.0, 1.0
      assert_in_delta hi, 13.0, 1.0
      been = [-60.0, -2.0, 3.0, 5.0, 8.0]

      # between where it stands and where the plates were taken: it goes, in the pose it is in
      ref = Enum.find(Mount.list(), &(&1.id == id))
      assert %{ok?: true, pose: :same} = Pointing.unknown_landing(KnownMount.at_ha(-40.0), snap, ctx)
      assert {:ok, d_ra, _d_dec} = Pointing.slew(ref, snap, KnownMount.at_ha(-40.0), ctx, track: false)
      Mount.stop(id)
      landed = snap.axes.ra.degrees + d_ra

      # and on either side of the pier the counterweight ends no higher than it has already been
      for cw <- [1, -1] do
        here = Model.counterweight(%{truth | cw: cw}, truth.signs, landed)
        highest = been |> Enum.map(&(cw * &1)) |> Enum.max()
        assert here <= highest + 5.5, "side #{cw}: the counterweight would end #{here}° from level, and has been no higher than #{highest}°"
      end

      # past the plates, toward the other side of the sky: refused, and the words say what to do
      assert %{ok?: false, upright?: false} = Pointing.unknown_landing(KnownMount.at_ha(40.0), snap, ctx)
      assert {:error, {:bar_unknown, _} = why} = Pointing.slew(ref, snap, KnownMount.at_ha(40.0), ctx, track: false)
      assert Pointing.refusal_words(why, "M31") =~ "past where it has stood tonight"
      assert Pointing.refusal_words(why, "M31") =~ "say below or above level"

      # the hold ends at the same edge
      to_axis = fn h -> (h - truth.off_ra) / truth.signs.ha_sign end
      refute Pointing.unknown_limit?(ctx, to_axis.(-30.0))
      assert Pointing.unknown_limit?(ctx, to_axis.(20.0))
      assert Pointing.unknown_limit?(ctx, to_axis.(-75.0))

      # a flip goes by the side: neither leg moves
      assert Pointing.home_leg(ref, snap, ctx) == {:error, :counterweight_unknown}

      # new pictures keep the answer, and someone who looks can still say
      assert {:ok, _} = Lineup.set_counterweight(id, snap, :below)
      assert Lineup.status(id).counterweight == :told
      refute Pointing.side_unknown?(snap, Pointing.context(DateTime.utc_now(), id))
    after
      Mount.stop(id)
    end

    test "the Counterweight card offers I Don't Know, and says what the mount does about it", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/setup/#{id}")
      assert html =~ "I Don&#39;t Know" or html =~ "I Don't Know"
      assert html =~ "never pick one"

      html = view |> element(~s(#counterweight button[phx-value-where="unknown"])) |> render_click()
      assert html =~ "Counterweight side unknown: Go To stays cautious"
      assert has_element?(view, ~s(#counterweight button[phx-value-where="unknown"][aria-checked="true"]))
      assert Lineup.status(id).counterweight == :unknown
    end

    # On a guess the hold's limit can be upside down: it would let the tube track on into the
    # tripod for as long as the target stays up. So no hold begins on a guess (#113).
    test "no hold begins while the side is a guess, and it says why; told, the hold goes by the limit", %{id: id, snap: snap} do
      ctx = Pointing.context(DateTime.utc_now(), id)
      # the guess has the counterweight past its limit here; the truth has it 60° below level
      assert Pointing.counterweight(ctx, snap.axes.ra.degrees) > Pointing.meridian_hard()
      {ra, dec} = Pointing.scope_radec(snap, ctx)
      here = %{name: "here", ra_deg: ra, dec_deg: dec}

      # guessed: not held, both axes left still, and why is there for the pages
      Tracker.track(id, here)
      wait(fn -> match?(%{why: :counterweight_unknown}, Tracker.ended(id)) end, 3_000)
      assert Tracker.status(id) == nil
      Process.sleep(600)
      refute Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running end)

      # told (wrongly, here) that it is above level: now it is known to be past the limit
      assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :above)
      Tracker.track(id, here)
      wait(fn -> match?(%{why: :meridian}, Tracker.ended(id)) end, 6_000)
      assert Tracker.status(id) == nil

      # told what it is, below level: the hold runs
      assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
      Tracker.track(id, here)
      wait(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
      assert Mount.snapshot(id).axes.ra.running
      assert Tracker.ended(id) == nil
      # and a picture taken under the hold belongs to the sky it shows
      refute Controller.Plates.capture(Mount.snapshot(id)).moving

      # what was told is taken back: the hold ends rather than trust a guess, both axes stopped
      assert Lineup.set_counterweight(id, Mount.snapshot(id), :guess) == {:ok, nil}
      wait(fn -> match?(%{why: :counterweight_unknown}, Tracker.ended(id)) end, 3_000)
      assert Tracker.status(id) == nil
      wait(fn -> not Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running end) end, 5_000)
    after
      Tracker.stop(id)
    end
  end

  # Told, the counterweight is the limit wherever the hold began. The plates here had the
  # counterweight low, and the mount stands a hair under the limit with the sky carrying it up.
  test "told, a hold that carries the counterweight up to the limit ends there", %{id: id} do
    KnownMount.align(id, Pointing.meridian_hard() - 0.02, [-40.0, -30.0, -20.0, -25.0])
    assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :above)
    snap = Mount.snapshot(id)
    ctx = Pointing.context(DateTime.utc_now(), id)
    assert Lineup.status(id).counterweight == :told
    assert Pointing.counterweight(ctx, snap.axes.ra.degrees) < Pointing.meridian_hard()

    {ra, dec} = Pointing.scope_radec(snap, ctx)
    Tracker.track(id, %{name: "here", ra_deg: ra, dec_deg: dec})
    # 0.02° of sky is five seconds
    wait(fn -> match?(%{why: :meridian}, Tracker.ended(id)) end, 20_000)
    assert Tracker.status(id) == nil
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
