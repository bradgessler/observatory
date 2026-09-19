defmodule Controller.OrbLiveTest do
  @moduledoc """
  The orb against a simulated mount: the three axes are drawn, the strips move
  one axis each, STOP stops, and the 3-D model agrees with the pointing model.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-test-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  describe "orb" do
    test "draws the three axes, the strips and STOP", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/controls/orb/#{id}")
      assert has_element?(view, "#orb-ax-ra")
      assert has_element?(view, "#orb-ax-dec")
      assert has_element?(view, "#orb-ax-scope")
      assert html =~ "pole"
      assert html =~ "tube"
      assert html =~ "RA · polar axis"
      assert html =~ "Dec axis"
      assert html =~ "STOP"
      refute html =~ "eyepiece mode"
    end

    test "says so until homed, then shows RA/Dec", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/controls/orb/#{id}")
      assert html =~ "assuming upright"
      Mount.set_home(id)
      assert_receive {:mount, %{homed: true}}, 2_000
      html = render(view)
      refute html =~ "assuming upright"
      assert html =~ "RA "
      assert html =~ "Dec "
    end

    test "a pull on the RA strip slews RA only; letting go stops it", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/orb/#{id}")
      render_hook(view, "stick", %{"x" => 1.0, "y" => 0.0, "mag" => 0.6, "axis" => "ra"})
      snap = Mount.snapshot(id)
      assert snap.axes.ra.running
      refute snap.axes.dec.running
      # the axis under the finger lights up
      assert has_element?(view, "#orb-ax-ra.live")
      refute has_element?(view, "#orb-ax-dec.live")
      render_hook(view, "stick_end", %{})
      refute Mount.snapshot(id).axes.ra.running
      refute has_element?(view, "#orb-ax-ra.live")
    end

    test "a running axis is drawn turning, with its rate", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/orb/#{id}")
      Mount.slew(id, :dec, 64)
      # wait for a snapshot with an observed velocity
      assert_receive {:mount, %{axes: %{dec: %{running: true, deg_per_s: v}}}} when v != 0.0, 2_000
      html = render(view)
      assert has_element?(view, "#orb-ax-dec.running")
      assert has_element?(view, "path.orbit-dec")
      assert html =~ ~r/[↻↺] \d+×/
      refute has_element?(view, "path.orbit-ra")
    end

    test "STOP is an instant stop", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/orb/#{id}")
      Mount.slew(id, :ra, 64)
      assert Mount.snapshot(id).axes.ra.running
      view |> element("button.stop-bar") |> render_click()
      refute Mount.snapshot(id).axes.ra.running
    end

    test "without an id it picks the first mount", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/controls/orb")
      assert html =~ "orb"
      assert html =~ "STOP" or html =~ id
    end
  end

  describe "geometry" do
    # The 3-D model (dec axis turned about the pole, tube tilted about the dec
    # axis) must land the tube where Pointing.scope_radec/2 → alt/az says it is,
    # on both sides of the pier and for either axis sign.
    test "the 3-D model agrees with the pointing model" do
      for {ha_sign, dec_sign} <- [{1, -1}, {-1, 1}, {1, 1}, {-1, -1}],
          {ra_deg, dec_deg} <- [{0.0, 0.0}, {30.0, 40.0}, {-60.0, -40.0}, {85.0, 120.0}, {-20.0, -150.0}] do
        ctx = %{
          now: ~U[2026-09-19 06:00:00Z],
          site: %{lat: 37.0, lon: -122.0, name: "test"},
          pointing: %{ha_sign: ha_sign, dec_sign: dec_sign},
          offset: %{"ra" => 0.0, "dec" => 0.0}
        }

        snap = %{
          homed: true,
          axes: %{
            ra: %{degrees: ra_deg, running: false, direction: :forward, deg_per_s: 0.0},
            dec: %{degrees: dec_deg, running: false, direction: :forward, deg_per_s: 0.0}
          }
        }

        scene = Controller.OrbLive.scene(snap, ctx)
        {mx, my, mz} = scene.scope.model
        {sx, sy, sz} = scene.scope.vec

        assert_in_delta mx, sx, 1.0e-6, "x for signs #{ha_sign}/#{dec_sign} at #{ra_deg}/#{dec_deg}"
        assert_in_delta my, sy, 1.0e-6, "y for signs #{ha_sign}/#{dec_sign} at #{ra_deg}/#{dec_deg}"
        assert_in_delta mz, sz, 1.0e-6, "z for signs #{ha_sign}/#{dec_sign} at #{ra_deg}/#{dec_deg}"
      end
    end

    test "at home the tube is on the pole and the dec axis is horizontal" do
      ctx = %{now: ~U[2026-09-19 06:00:00Z], site: %{lat: 37.0, lon: -122.0, name: "t"}, pointing: %{ha_sign: 1, dec_sign: -1}, offset: %{"ra" => 0.0, "dec" => 0.0}}
      snap = %{homed: false, axes: %{ra: %{degrees: 0.0, running: false}, dec: %{degrees: 0.0, running: false}}}
      scene = Controller.OrbLive.scene(snap, ctx)
      assert_in_delta scene.scope.alt, 37.0, 1.0e-6
      assert_in_delta scene.scope.az, 0.0, 1.0e-6
      assert scene.radec == nil
    end
  end
end
