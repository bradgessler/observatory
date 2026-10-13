defmodule Controller.ScopeNowTest do
  @moduledoc """
  What the telescope is doing, on every page (13 October: "whenever I hit Go
  To I could not tell the telescope was moving"). A slew is said in words, in
  the bar at the top of every page, with its own STOP.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.ScopeNow

  defp snap(axes, more \\ %{}) do
    axis = fn a -> Map.merge(%{running: false, goto_pending: false, deg_per_s: 0.0, degrees: 10.0}, a) end
    Map.merge(%{id: "m", connected: true, tracking: :off, axes: %{ra: axis.(axes[:ra] || %{}), dec: axis.(axes[:dec] || %{})}}, more)
  end

  describe "the summary" do
    test "a Go To in flight is slewing, by name when the tracker has one" do
      going = snap(%{ra: %{running: true, goto_pending: true, deg_per_s: 3.0}})
      assert %{state: :slewing, words: "Slewing to M33 Triangulum", target: "M33 Triangulum"} = ScopeNow.summary(going, %{name: "M33 Triangulum"})
      assert %{state: :slewing, words: "Slewing"} = ScopeNow.summary(going)
      assert %{state: :slewing, words: "Slewing to the next alignment picture"} = ScopeNow.summary(going, nil, true)
    end

    test "held on a target it is tracking; driven with nothing held it is moving; else still" do
      holding = snap(%{ra: %{running: true, deg_per_s: 0.0042}})
      assert %{state: :tracking, words: "Tracking Saturn"} = ScopeNow.summary(holding, %{name: "Saturn"})
      assert %{state: :tracking, words: "Tracking"} = ScopeNow.summary(snap(%{}, %{tracking: :sidereal}))
      assert %{state: :moving, words: "Moving"} = ScopeNow.summary(snap(%{dec: %{running: true, deg_per_s: -1.2}}))
      assert %{state: :still, words: "Still"} = ScopeNow.summary(snap(%{}))
      assert %{state: :offline, words: "Not answering"} = ScopeNow.summary(%{id: "m", connected: false})
    end
  end

  describe "on a page" do
    setup do
      id = "sim-now-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(id)
      assert_receive {:mount, %{connected: true}}, 2_000
      %{id: id}
    end

    test "the bar says what the telescope is doing, goes loud on a slew with its own STOP, and STOP stops it", %{conn: conn, id: id} do
      ScopeNow.subscribe()
      conn = Plug.Test.init_test_session(conn, %{"telescope" => id})
      {:ok, view, _html} = live(conn, ~p"/tonight/#{id}")
      assert_receive {:scope_now, ^id, %{state: :still}}, 8_000
      assert has_element?(view, "#scope-now.now-still strong", "Still")
      refute has_element?(view, "#scope-now button")

      :ok = Mount.goto_relative(id, :ra, 40.0)
      assert_receive {:scope_now, ^id, %{state: :slewing, words: "Slewing"}}, 3_000
      assert has_element?(view, ~s(#scope-now.now-slewing strong[role="status"]), "Slewing")
      assert has_element?(view, ~s(#scope-now button[phx-click="scope_stop"]), "STOP")

      view |> element(~s(#scope-now button[phx-click="scope_stop"])) |> render_click()
      assert_receive {:scope_now, ^id, %{state: :still}}, 5_000
      refute Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running end)
      assert has_element?(view, "#scope-now.now-still")
    end
  end
end
