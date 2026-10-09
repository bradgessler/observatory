defmodule Controller.Sky.FlipTest do
  @moduledoc """
  The last Go To of the first field night: the Moon, past the meridian on a
  mount that was never zeroed. Go To looked at one pose, found its
  counterweight above level, and refused. The other pose, a meridian flip,
  had the counterweight well down and was never considered. And the hold,
  with no soft limits, would have carried the tube into the legs.

  Now: the counterweight's height comes from the model (which way is down
  read from where the alignment points were taken), Go To picks the pose that
  keeps it down, asks before a flip, flips in two legs with a stop at home,
  and the answers on a page (Reach) say all of that before anyone taps.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.{Astro, Lineup, Model, Moves, Pointing, Reach}

  @site %{lat: 40.0, lon: -105.0, name: "test"}
  @signs %{ha_sign: 1, dec_sign: -1}

  defp model, do: Model.ideal(@site.lat) |> Map.merge(%{signs: @signs, cw: 1})

  defp ctx(now \\ ~U[2026-09-26 06:00:00Z]),
    do: %{
      now: now,
      site: @site,
      pointing: @signs,
      offset: %{"ra" => 0.0, "dec" => 0.0},
      model: model(),
      mount: "t"
    }

  # an object at hour angle `ha`, declination `dec`, right now
  defp at_ha(c, ha, dec \\ 20.0),
    do: %{
      id: "t#{ha}",
      name: "Target #{ha}",
      ra_deg: Astro.norm360(Astro.lst_deg(c.now, @site.lon) - ha),
      dec_deg: dec
    }

  defp snap(ra, dec, extra \\ %{}),
    do:
      Map.merge(
        %{
          id: "t",
          connected: true,
          homed: false,
          tracking: :off,
          axes: %{ra: %{degrees: ra, running: false}, dec: %{degrees: dec, running: false}}
        },
        extra
      )

  describe "the counterweight" do
    test "is level on the meridian, straight down a quarter turn east, straight up a quarter turn west" do
      m = model()
      assert_in_delta Model.counterweight(m, @signs, 0.0), 0.0, 1.0e-9
      assert_in_delta Model.counterweight(m, @signs, -90.0), -90.0, 1.0e-9
      assert_in_delta Model.counterweight(m, @signs, 90.0), 90.0, 1.0e-9
      # the far side of the pier: the same heights, mirrored
      assert_in_delta Model.counterweight(m, @signs, -160.0), -20.0, 1.0e-9
    end

    test "which way is down is read from where the alignment points were taken" do
      m = Map.delete(model(), :cw)
      # centred east of the meridian (H < 0): down is H = -90
      assert Model.cw_down(m, @signs, [-40.0, -20.0, -13.0, 15.0]) == 1
      # the same sky from the other side of the pier
      assert Model.cw_down(m, @signs, [140.0, 160.0, 167.0, -165.0]) == -1
    end

    test "a fit that lands over the zenith reads the usual way" do
      over = %{axis_alt: 145.465, axis_az: -185.487, off_ra: 0.0, off_dec: 0.0}
      c = Model.canonical(over)
      assert_in_delta c.axis_alt, 34.535, 0.001
      assert_in_delta c.axis_az, 354.513, 0.001
      assert Model.axis_distance(over, c) < 1.0e-6
    end

    test "the hold's limit: anywhere the counterweight is past it" do
      hard = Pointing.meridian_hard()
      assert Pointing.hold_limit?(40.1)
      assert Pointing.hold_limit?(hard + 0.01)
      refute Pointing.hold_limit?(hard - 0.01)
      refute Pointing.hold_limit?(-60.0)
    end

    # #113: the side was guessed upside down twice, so on a guess nothing moves by it
    test "the side is a guess only on a mount with no home, whose alignment was never told" do
      told = ctx()
      guessed = put_in(told.model[:cw_told], false)

      assert Pointing.side_guessed?(snap(0.0, 0.0), guessed)
      refute Pointing.side_guessed?(snap(0.0, 0.0), told)
      # home set: home is where the counterweight hangs straight down, so nothing rests on a guess
      refute Pointing.side_guessed?(snap(0.0, 0.0, %{homed: true}), guessed)
      # no alignment: Go To has nothing to pick a side by (it refuses as not homed)
      refute Pointing.side_guessed?(snap(0.0, 0.0), %{told | model: nil})
    end
  end

  describe "where Go To lands" do
    test "east of the meridian it stays on this side" do
      c = ctx()
      plan = Pointing.landing(at_ha(c, -30), snap(-10.0, -60.0), c)
      assert plan.pose == :same
      assert plan.cw < 0
    end

    test "a little past the meridian is still this side" do
      c = ctx()
      assert Pointing.landing(at_ha(c, 2), snap(-10.0, -60.0), c).pose == :same
    end

    test "well past, it flips to the pose with the counterweight down, turning through down, not up" do
      c = ctx()
      plan = Pointing.landing(at_ha(c, 30), snap(-10.0, -60.0), c)
      assert plan.pose == :flip
      assert_in_delta plan.cw_same, 30.0, 0.5
      assert_in_delta plan.cw, -30.0, 0.5
      # RA goes east, through counterweight-down, never over the top
      assert plan.d_ra < 0 and plan.d_ra > -180
      # Dec through the pole (0 in this model), not through the ground
      assert plan.dec > 0 and plan.dec < 180
    end

    test "watched, it stays on this side up to the hard limit, and no further" do
      c = ctx()
      assert Pointing.landing(at_ha(c, 15), snap(-10.0, -60.0), c, watched: true).pose == :same
      assert Pointing.landing(at_ha(c, 25), snap(-10.0, -60.0), c, watched: true).pose == :flip
    end

    test "Dec never swings through the point opposite the pole" do
      c = ctx()
      # counts that have run past 180 from where the mount woke up
      plan = Pointing.landing(at_ha(c, -30), snap(-10.0, -200.0), c)
      d_from = -1 * -200.0
      d_to = -1 * plan.dec

      refute Enum.any?([180, -180, 540], fn g ->
               g > min(d_from, d_to) and g < max(d_from, d_to)
             end)
    end
  end

  describe "what the page says before anyone taps" do
    @lock %{n: 8, rms_arcmin: 6.8, solved?: true}

    test "no mount, then no lock, each with the thing to do" do
      c = ctx()
      o = at_ha(c, -30)
      r = Reach.of(o, nil, c, trees?: false)
      assert r.go.text =~ "No mount"
      r = Reach.of(o, snap(0.0, 0.0), %{c | model: nil}, trees?: false)
      assert r.go.text =~ "Not aligned"
      assert r.track.text =~ "Needs an alignment"
      assert r.go.mark == "×"
    end

    test "east of the meridian: lands inside the field, held until the counterweight's limit" do
      c = ctx()
      r = Reach.of(at_ha(c, -30), snap(-10.0, -60.0), c, trees?: false, lock: @lock, field: 72)
      assert r.look.mark == "✓"
      assert r.go.text =~ "±14′"
      assert r.go.tone == :good
      assert r.track.text =~ "counterweight reaches its limit"
    end

    test "past the meridian: the flip is said up front, and the hold then lasts until it sets" do
      c = ctx()
      r = Reach.of(at_ha(c, 30), snap(-10.0, -60.0), c, trees?: false, lock: @lock, field: 72)
      assert r.go.text =~ "Flips the mount first"
      assert r.track.text =~ "until it sets"
    end

    # #113: the page can't promise what the mount won't do, and on a guess it won't move
    test "with the counterweight's side a guess, Go To and Track say they wait for it, and what to answer" do
      c = ctx()
      o = at_ha(c, -30)
      guessed = Reach.of(o, snap(-10.0, -60.0), put_in(c.model[:cw_told], false), trees?: false, lock: @lock)
      assert guessed.go.text =~ "is the counterweight below or above level right now?"
      assert guessed.go.mark == "×"
      assert guessed.track.text =~ "Waits for the same answer"
      refute guessed.go.text =~ "lands within"

      # told: what Go To and the hold will do, as before
      told = Reach.of(o, snap(-10.0, -60.0), c, trees?: false, lock: @lock)
      assert told.go.text =~ "±14′"
      assert told.track.text =~ "counterweight reaches its limit"
    end

    test "a hold that stopped at the limit says why and what to do" do
      c = ctx()
      o = at_ha(c, 30)
      ended = %{name: o.name, why: :meridian, at: c.now}
      r = Reach.of(o, snap(-10.0, -60.0), c, trees?: false, lock: @lock, ended: ended)
      assert r.track.text =~ "counterweight reached its limit"
      assert r.track.text =~ "flips"
    end
  end

  describe "the flip on a real (simulated) mount" do
    setup do
      id = "sim-flip-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(id)
      assert_receive {:mount, %{connected: true}}, 2_000

      # three points centred east of the meridian, on an ideal mount
      site = Pointing.site()
      now = DateTime.utc_now()
      lst = Astro.lst_deg(now, site.lon)
      m = Model.ideal(site.lat)

      points =
        for ha <- [-60.0, -40.0, -20.0] do
          ra = Astro.norm360(lst - ha)
          {tr, td} = Model.encoders_radec(m, @signs, ra, 30.0, site.lat, lst)

          %{
            "name" => "p#{ha}",
            "at" => DateTime.to_iso8601(now),
            "theta_ra" => tr,
            "theta_dec" => td,
            "ra_deg" => ra,
            "dec_deg" => 30.0
          }
        end

      Controller.Settings.put("pointing", %{"ha_sign" => 1, "dec_sign" => -1})
      Lineup.replace(id, points, nil)
      on_exit(fn -> Lineup.clear(id) end)
      # every point east of the meridian: the guess is right here, and someone at the mount says so
      # (on a guess nothing moves, #113)
      Controller.Test.KnownMount.confirm_guess(id)
      %{id: id, site: site}
    end

    # a bright star 30 to 60 degrees past the meridian and well up, whenever the test runs
    defp west_star(site) do
      lst = Astro.lst_deg(DateTime.utc_now(), site.lon)

      Controller.Sky.Catalog.stars(3.0)
      |> Enum.find(fn s ->
        ha = Astro.hour_angle(lst, s.ra_deg)
        {alt, _} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, lst)
        ha > 30 and ha < 60 and alt > 25
      end)
    end

    test "Go To asks first; the flip goes home, stops, and goes on only when told", %{
      conn: conn,
      id: id,
      site: site
    } do
      assert Lineup.model(id), "the three points fit"
      star = west_star(site) || flunk("no bright star 30-60° past the meridian right now")

      {:ok, view, _} = live(conn, "/object/#{star.id}?mount=#{id}")
      html = render_click(view, "slew", %{})
      assert html =~ "on the other side of the meridian"
      assert html =~ "Flip, in Two Legs"
      refute Mount.snapshot(id).axes.ra[:goto_pending]

      render_click(view, "flip", %{})
      assert %{leg: :home} = Moves.pending(id)

      # leg 1 lands at home: counterweight down, tube at the pole
      wait(fn -> match?(%{leg: :waiting}, Moves.pending(id)) end, 30_000)
      ctx = Pointing.context(DateTime.utc_now(), id)
      assert_in_delta Pointing.counterweight(ctx, Mount.snapshot(id).axes.ra.degrees), -90.0, 1.0
      html = render(view)
      assert html =~ "Is the way clear?"

      html = render_click(view, "flip_on", %{})
      assert html =~ "on the other side of the pier"
      assert Moves.pending(id) == nil
    after
      Controller.Sky.Tracker.stop(id)
    end

    test "STOP between the legs forgets the flip", %{conn: conn, id: id, site: site} do
      star = west_star(site) || flunk("no bright star 30-60° past the meridian right now")
      {:ok, view, _} = live(conn, "/object/#{star.id}?mount=#{id}")
      render_click(view, "slew", %{})
      render_click(view, "flip", %{})
      :ok = Mount.stop(id)
      wait(fn -> Moves.pending(id) == nil end, 3_000)
    end
  end

  defp wait(ok?, timeout) do
    deadline = System.monotonic_time(:millisecond) + timeout

    Stream.repeatedly(fn -> ok?.() end)
    |> Enum.find(fn v ->
      v or System.monotonic_time(:millisecond) > deadline or (Process.sleep(100) && false)
    end)
    |> Kernel.||(flunk("never happened"))
  end
end
