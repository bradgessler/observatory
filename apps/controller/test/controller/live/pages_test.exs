defmodule Controller.PagesTest do
  @moduledoc """
  Every page renders against a simulated mount and reacts to the things a
  phone would do. The simulator speaks the real wire protocol, so this is the
  whole stack minus the cable.
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

  describe "keypad" do
    test "renders one strip per axis and STOP", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/#{id}")
      assert html =~ "around the polar axis"
      assert html =~ "around the dec axis"
      assert html =~ "STOP"
      # not blended by default
      refute html =~ "as you see it (both motors)"
      assert has_element?(view, "#strip-ra")
    end

    test "a pull on the RA strip slews RA only; letting go stops it", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      render_hook(view, "stick", %{"x" => 1.0, "y" => 0.0, "mag" => 0.6, "axis" => "ra"})
      snap = Mount.snapshot(id)
      assert snap.axes.ra.running
      refute snap.axes.dec.running
      render_hook(view, "stick_end", %{})
      refute Mount.snapshot(id).axes.ra.running
    end

    test "STOP is an instant stop", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      Mount.slew(id, :dec, 64)
      assert Mount.snapshot(id).axes.dec.running
      view |> element("button.stop-bar") |> render_click()
      refute Mount.snapshot(id).axes.dec.running
    end

    test "arrow keys drive the strips without JavaScript", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      render_keydown(view, "keydown", %{"key" => "ArrowRight"})
      assert Mount.snapshot(id).axes.ra.running
      render_keyup(view, "keyup", %{"key" => "ArrowRight"})
      refute Mount.snapshot(id).axes.ra.running
    end
  end

  describe "sky" do
    test "renders the map, tonight and horizon tabs", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/sky/#{id}")
      assert html =~ "Tonight"
      assert view |> element("button", "Tonight") |> render_click() =~ "Above your tree line"
      assert view |> element("button", "Horizon") |> render_click() =~ "aperture"
    end

    test "slewing before home explains itself", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/sky/#{id}")
      render_click(view, "pick", %{"id" => "m13"})
      assert render_click(view, "goto", %{}) =~ "set home"
    end
  end

  describe "object" do
    test "shows a blurb and slew button", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/object/m31?mount=#{id}")
      assert html =~ "Andromeda"
      assert html =~ "2.5 million light-years"
      assert html =~ "Slew"
    end

    test "unknown object is a soft 404", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/object/nope")
      assert html =~ "Nothing called"
    end
  end

  describe "setup and devices" do
    test "setup shows modes and can set home", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/setup/#{id}")
      assert html =~ "Sync offset"
      render_click(view, "home", %{})
      assert Mount.snapshot(id).homed
    end

    test "devices lists the simulated mount", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/devices")
      assert html =~ id
      assert html =~ "Drive it"
    end
  end

  describe "docs" do
    test "markdown pages render", %{conn: conn} do
      assert get(conn, "/docs/magnitude") |> html_response(200) =~ "<h1>"
      assert get(conn, "/docs/nope") |> response(404)
    end
  end
end
