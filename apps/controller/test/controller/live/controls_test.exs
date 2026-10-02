defmodule Controller.ControlsTest do
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-controls-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "every page lives at one address; the bench's old ones land there, with the mount", %{conn: conn, id: id} do
    assert redirected_to(get(conn, "/bench/sky?mount=#{id}"), 301) == "/sky/#{id}"
    assert redirected_to(get(conn, "/bench/dpad?mount=#{id}"), 301) == "/controls/dpad/#{id}"
    assert redirected_to(get(conn, "/bench/gamepad?mount=#{id}"), 301) == "/input?mount=#{id}"
    assert redirected_to(get(conn, "/bench/watch"), 301) == "/cameras/observatory"
    assert redirected_to(get(conn, "/bench"), 301) == "/"
  end

  test "the plain keypad at its own address", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/controls/dpad/#{id}")
    assert html =~ "toward pole"
    assert html =~ "800×"
  end

  test "plain keypad: holding an arrow moves one axis, release stops it", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/controls/dpad/#{id}")
    render_hook(view, "stick", %{"x" => 1, "y" => 0, "mag" => 1})
    snap = Mount.snapshot(id)
    assert snap.axes.ra.running
    refute snap.axes.dec.running
    render_hook(view, "stick_end", %{})
    refute Mount.snapshot(id).axes.ra.running
  end

  test "game controller surface renders server-side state only", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/input?mount=#{id}")
    assert html =~ "Watch Only"
    refute html =~ "phx-hook=\"Gamepad\""
  end
end
