defmodule Controller.AlignmentTest do
  @moduledoc """
  One alignment summary per telescope, the same everywhere: in the sidebar,
  in the switcher, in the Alignment pages' toolbar. And the Controls pages
  say what the mount is doing and where it points.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Alignment

  setup do
    id = "sim-align-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "a new mount isn't aligned; home set says so, with no margin yet", %{id: id} do
    s = Alignment.summary(id)
    assert s.state == :none
    assert s.words == "Not aligned"
    assert s.rings == 0

    :ok = Mount.set_home(id)
    s = Alignment.summary(id)
    assert s.state == :home
    assert s.words == "Home set · no points"
    assert s.rings == 0
  end

  test "the margin lights the rings: each goal it meets, loosest first" do
    for {margin, rings} <- [{40.0, 0}, {25.0, 1}, {6.0, 2}, {1.5, 3}] do
      met = Enum.filter(Alignment.tiers(), fn {_, lim, _} -> margin <= lim end)
      assert length(met) == rings, "#{margin}′ should light #{rings}"
    end
  end

  test "a home set reaches every page live, with no page asking for it", %{conn: conn, id: id} do
    conn = Plug.Test.init_test_session(conn, %{"telescope" => id})
    {:ok, view, html} = live(conn, "/alignment/#{id}")
    # the sidebar's line and the toolbar's status
    assert html =~ "al-chip"
    assert html =~ "al-bar"
    assert html =~ "Not aligned"

    :ok = Mount.set_home(id)
    # the watcher notices the home and says so; the page redraws from the broadcast
    Process.sleep(300)
    assert render(view) =~ "Home set · no points"
  end

  test "the Controls pages say what the mount is doing and where it points", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/keypad/#{id}")
    assert html =~ "ctl-status"
    assert html =~ "Still"
    assert html =~ "Not on the sky yet"
  end
end
