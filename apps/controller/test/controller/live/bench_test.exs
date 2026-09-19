defmodule Controller.BenchTest do
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-bench-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "bench shows the scope state and every surface", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/bench?mount=#{id}")
    assert html =~ "scope-status"
    assert html =~ id
    for name <- ["Axis strips", "Plain keypad", "Orb", "Game controller", "Sky"], do: assert(html =~ name)
    # default surface is the strips, rendered nested without its own header
    assert html =~ "around the polar axis"
  end

  test "switching surfaces renders the plain keypad nested", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/bench/dpad?mount=#{id}")
    html = render(view)
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
    assert html =~ "watch only"
    refute html =~ "phx-hook=\"Gamepad\""
  end
end
