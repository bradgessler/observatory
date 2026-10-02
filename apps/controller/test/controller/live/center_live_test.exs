defmodule Controller.CenterLiveTest do
  @moduledoc """
  Center: arrows that move what you see, through a view map that one tap
  can flip, and Centered that records where the axes were.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.CenterLive

  setup do
    id = "sim-center-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Controller.Settings.put("view_map", CenterLive.default_view_map())
    on_exit(fn -> Controller.Settings.put("view_map", CenterLive.default_view_map()) end)
    %{id: id}
  end

  test "each way in the view is an axis and a sign; up is down reversed" do
    assert CenterLive.move_for("down", 3) == {:ra, 0.05}
    assert CenterLive.move_for("up", 3) == {:ra, -0.05}
    assert CenterLive.move_for("right", 3) == {:dec, -0.05}
    assert CenterLive.move_for("left", 3) == {:dec, 0.05}

    # a turned diagonal: down moves the view right, right moves it up
    turned = CenterLive.turn(CenterLive.default_view_map())
    assert CenterLive.move_for("right", 3, turned) == {:ra, 0.05}
    assert CenterLive.move_for("up", 3, turned) == {:dec, -0.05}
    assert Enum.reduce(1..4, CenterLive.default_view_map(), fn _, m -> CenterLive.turn(m) end) == CenterLive.default_view_map()

    flipped = CenterLive.flip(CenterLive.default_view_map(), "right")
    assert CenterLive.move_for("right", 3, flipped) == {:dec, 0.05}
    assert CenterLive.move_for("down", 3, flipped) == {:ra, 0.05}
  end

  test "a pull is a speed: a crawl past the dead zone, 8× at the rim, never a slew" do
    assert CenterLive.speed(0.0) == 0.0
    assert_in_delta CenterLive.speed(0.001), 0.5, 0.01
    assert_in_delta CenterLive.speed(1.0), 8.0, 1.0e-9
    assert CenterLive.speed(3.0) == CenterLive.speed(1.0)
  end

  test "RA carries on from tracking, so a drag moves the view against the sky" do
    # view down is RA forward: tracking at 1× plus 2× more
    assert CenterLive.drag_rates(0.0, -1.0, 2.0, CenterLive.default_view_map(), :sidereal) == [ra: 3.0]
    # view up at 1× against sidereal tracking holds RA still
    assert [ra: r] = CenterLive.drag_rates(0.0, 1.0, 1.0, CenterLive.default_view_map(), :sidereal)
    assert_in_delta r, 0.0, 1.0e-9
    # view right is Dec back; RA isn't touched, so it keeps tracking
    assert CenterLive.drag_rates(1.0, 0.0, 4.0, CenterLive.default_view_map(), :sidereal) == [dec: -4.0]
  end

  test "a touch drives one direction: the first pull decides, a drifting thumb doesn't add the other axis", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/controls/center/#{id}")

    # starts mostly up, then drifts well to the left: still up/down only
    render_hook(view, "stick", %{"x" => -0.2, "y" => 0.98, "mag" => 0.6})
    html = render_hook(view, "stick", %{"x" => -0.8, "y" => 0.6, "mag" => 0.6})
    assert html =~ "up/down only until you lift"
    refute Mount.snapshot(id).axes.dec.running
    assert Mount.snapshot(id).axes.ra.running

    # lift, touch again sideways: now left/right
    render_hook(view, "stick_end", %{})
    wait_until(fn -> not Mount.snapshot(id).axes.ra.running end)
    render_hook(view, "stick", %{"x" => -1.0, "y" => 0.1, "mag" => 0.6})
    assert Mount.snapshot(id).axes.dec.running
    refute Mount.snapshot(id).axes.ra.running
    render_hook(view, "stick_end", %{})
    wait_until(fn -> not Mount.snapshot(id).axes.dec.running end)
  end

  test "arrow keys move the view the mapped way while held; Escape is STOP", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/controls/center/#{id}")

    # view down is RA forward
    render_keydown(view, "keydown", %{"key" => "ArrowDown"})
    assert Mount.snapshot(id).axes.ra.running
    refute Mount.snapshot(id).axes.dec.running
    render_keyup(view, "keyup", %{"key" => "ArrowDown"})
    refute Mount.snapshot(id).axes.ra.running

    # view right is Dec back
    render_keydown(view, "keydown", %{"key" => "ArrowRight"})
    assert Mount.snapshot(id).axes.dec.running
    render_keydown(view, "keydown", %{"key" => "Escape"})
    refute Mount.snapshot(id).axes.dec.running
  end

  test "a thumb on the pad drives the mapped axis; lifting it stops; Backwards flips; Centered says so", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/controls/center/#{id}")
    assert html =~ "Centered"
    assert html =~ "Put a thumb on the eyepiece"

    # pull down, hard: the view goes down, which is RA forward
    html = render_hook(view, "stick", %{"x" => 0.0, "y" => -1.0, "mag" => 1.0})
    assert html =~ "Moving the view down at 8.0×"
    assert Mount.snapshot(id).axes.ra.running
    refute Mount.snapshot(id).axes.dec.running

    render_hook(view, "stick_end", %{})
    wait_until(fn -> not Mount.snapshot(id).axes.ra.running end)

    # pull right: Dec, and lifting stops it
    render_hook(view, "stick", %{"x" => 1.0, "y" => 0.0, "mag" => 0.5})
    assert Mount.snapshot(id).axes.dec.running
    render_hook(view, "stick_end", %{})
    wait_until(fn -> not Mount.snapshot(id).axes.dec.running end)

    render_click(view, "flip", %{"pair" => "down"})
    assert Controller.Settings.get("view_map")["down"] == ["ra", -1]

    Telescope.subscribe("center")
    assert render_click(view, "centered", %{}) =~ "Centered at"
    assert_receive {:centered, %{mount: ^id, ra: _, dec: _}}, 1_000
  end

  defp wait_until(f, tries \\ 100) do
    cond do
      f.() -> :ok
      tries == 0 -> flunk("never settled")
      true -> Process.sleep(50) && wait_until(f, tries - 1)
    end
  end
end
