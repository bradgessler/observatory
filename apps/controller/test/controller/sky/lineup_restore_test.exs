defmodule Controller.Sky.LineupRestoreTest do
  @moduledoc """
  Nothing is thrown away by a reset (12 October: "when we reset it, keep the
  old one around and make it so we can bring it back"). Clearing, forgetting
  a point, or a new alignment replacing the old one sets the old one aside,
  and Restore puts it back, on the pages that can reset one.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.Lineup

  setup do
    id = "sim-restore-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    # an alignment here can correct the global axis signs: put them back for the modules after this one
    pointing = Controller.Settings.get("pointing")

    on_exit(fn ->
      Lineup.clear(id)
      Controller.Settings.put("lineup_set_aside", Map.delete(Controller.Settings.get("lineup_set_aside", %{}), id))
      Controller.Settings.put("mount_power_on", Map.delete(Controller.Settings.get("mount_power_on", %{}), id))
      Controller.Settings.put("pointing", pointing)
    end)

    %{id: id}
  end

  defp point(name, ra, dec, tr, td, at \\ DateTime.utc_now()),
    do: %{"name" => name, "at" => DateTime.to_iso8601(at), "theta_ra" => tr, "theta_dec" => td, "ra_deg" => ra, "dec_deg" => dec}

  defp three, do: [point("a", 279.23, 38.78, 10.0, 40.0), point("b", 297.70, 8.87, 30.0, 70.0), point("c", 310.36, 45.28, 20.0, 30.0)]

  test "a cleared alignment is set aside, and restore brings it back as it was", %{id: id} do
    Lineup.replace(id, three(), nil)
    was = Lineup.model(id)
    assert was
    assert Lineup.set_aside(id) == []

    :ok = Lineup.clear(id)
    assert Lineup.status(id).n == 0
    refute Lineup.model(id)
    assert [%{index: 0, n: 3, why: "it was cleared", holds?: true, set_aside_at: %DateTime{}}] = Lineup.set_aside(id)
    assert %{n: 3} = Lineup.restorable(id)

    assert {:ok, %{n: 3}} = Lineup.restore(id)
    assert Lineup.model(id) == was
    assert Enum.map(Lineup.samples(id), & &1["name"]) == ~w(a b c)
    # brought back, it is no longer set aside; and with nothing replaced there is nothing new to bring back
    assert Lineup.set_aside(id) == []
    assert Lineup.restore(id) == {:error, :nothing}
  end

  test "a run's pictures arriving one fit at a time are one alignment growing, not a reset each", %{id: id} do
    [a, b, _c] = three()
    Lineup.replace(id, three(), nil)
    Lineup.clear(id)

    # a new run: one picture, then two, then three (Plates.use_alignment hands over all of them each time)
    d = point("d", 200.0, 30.0, 5.0, 20.0)
    e = point("e", 215.0, 35.0, 20.0, 25.0)
    Lineup.replace(id, [d], nil)
    Lineup.replace(id, [d, e], nil)
    Lineup.replace(id, [d, e, point("f", 230.0, 40.0, 35.0, 30.0)], nil)

    # only the alignment that was cleared is aside: the run's own earlier fits are not resets
    assert [%{n: 3, why: "it was cleared"}] = Lineup.set_aside(id)

    # another alignment altogether replaces the run's: now that one is aside as well, newest first
    Lineup.replace(id, [a, b], nil)
    assert [%{n: 3, why: "a new alignment replaced it"}, %{n: 3, why: "it was cleared"}] = Lineup.set_aside(id)
  end

  test "restore sets aside what it replaces, so a restore can be undone", %{id: id} do
    Lineup.replace(id, three(), nil)
    first = Lineup.model(id)
    two = [point("d", 200.0, 30.0, 5.0, 20.0), point("e", 215.0, 35.0, 20.0, 25.0)]
    Lineup.replace(id, two, nil)
    second = Lineup.model(id)
    assert first != second

    assert {:ok, %{n: 3}} = Lineup.restore(id)
    assert Lineup.model(id) == first
    assert [%{n: 2, why: "an earlier alignment was restored"}] = Lineup.set_aside(id)

    assert {:ok, %{n: 2}} = Lineup.restore(id)
    assert Lineup.model(id) == second
  end

  test "forgetting a point keeps the alignment as it was", %{id: id} do
    Lineup.replace(id, three(), nil)
    was = Lineup.model(id)
    Lineup.drop(id, 2)
    assert Lineup.status(id).n == 2
    assert [%{n: 3, why: "a point was forgotten"}] = Lineup.set_aside(id)
    assert {:ok, %{n: 3}} = Lineup.restore(id)
    assert Lineup.model(id) == was
  end

  test "an alignment from before the mount was switched off and on is kept but cannot be brought back", %{id: id} do
    Lineup.replace(id, three(), nil)
    Lineup.clear(id)
    # the mount is switched on again: the counts that alignment was made in are gone
    Controller.Settings.put("mount_power_on", Map.put(Controller.Settings.get("mount_power_on", %{}), id, System.os_time(:millisecond) + 1_000))

    assert [%{n: 3, holds?: false}] = Lineup.set_aside(id)
    assert Lineup.restorable(id) == nil
    assert Lineup.restore(id) == {:error, :nothing}
    assert Lineup.restore(id, 0) == {:error, :stale}
    assert Lineup.status(id).n == 0
  end

  test "only the last five are kept", %{id: id} do
    for i <- 1..7 do
      Lineup.replace(id, [point("p#{i}", 200.0 + i, 30.0, 5.0 + i, 20.0)], nil)
      Lineup.clear(id)
    end

    assert length(Lineup.set_aside(id)) == 5
  end

  describe "on the pages" do
    test "Align by Stars: Clear, then Restore, and the points are back", %{conn: conn, id: id} do
      :ok = Mount.set_home(id)
      assert_receive {:mount, %{homed: true, homed_at: home_at}}, 2_000
      Lineup.replace(id, three(), home_at)

      {:ok, view, html} = live(conn, ~p"/controls/align/#{id}")
      refute html =~ "Alignment set aside"

      html = render_click(view, "clear")
      assert html =~ "Alignment cleared. Restore brings it back"
      assert html =~ "Alignment set aside just now"
      assert html =~ "3 points agree to" and html =~ "It was cleared."
      assert Lineup.status(id).n == 0

      html = view |> element("#alignment-set-aside button", "Restore") |> render_click()
      assert html =~ "Alignment restored: 3 points agree to"
      refute html =~ "Alignment set aside"
      assert Lineup.status(id).n == 3
    end

    test "the Status page and Align with the Camera offer the same Restore", %{conn: conn, id: id} do
      Lineup.replace(id, three(), nil)
      Lineup.clear(id)

      for path <- ["/alignment/#{id}", "/align/camera/#{id}"] do
        {:ok, view, html} = live(conn, path)
        assert html =~ "Alignment set aside", path
        assert has_element?(view, "#alignment-set-aside button", "Restore"), path
      end

      {:ok, view, _} = live(conn, "/align/camera/#{id}")
      assert view |> element("#alignment-set-aside button", "Restore") |> render_click() =~ "Alignment restored: 3 points agree to"
      assert Lineup.status(id).n == 3
    end
  end
end
