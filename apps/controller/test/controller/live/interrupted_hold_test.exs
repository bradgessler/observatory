defmodule Controller.InterruptedHoldTest do
  @moduledoc """
  The box went down in the middle of a hold (a firmware upgrade, on the
  first night): the home page offers it back as a Go To someone taps, and
  forgets it on request or when the mount itself was switched on since (#99).
  A switched-off mount says so calmly, with a simulator one tap away.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Settings
  alias Controller.Sky.Tracker

  setup do
    id = "sim-ih-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    on_exit(fn -> Settings.put("hold", Map.delete(Settings.get("hold", %{}), id)) end)
    %{id: id}
  end

  defp held(id, since) do
    Settings.put("hold", Map.put(Settings.get("hold", %{}), id, %{"target" => %{"id" => "m13", "name" => "M13", "ra_deg" => 250.42, "dec_deg" => 36.46}, "since" => DateTime.to_iso8601(since)}))
  end

  test "a hold the box went down in the middle of is offered back, and can be forgotten", %{conn: conn, id: id} do
    held(id, DateTime.utc_now())
    assert %{target: %{name: "M13"}} = Tracker.interrupted(id)

    {:ok, view, html} = live(conn, "/")
    assert html =~ "Was holding M13 when the box restarted"
    assert html =~ "Go To M13"

    html = render_click(view, "forget_hold", %{"id" => id})
    refute html =~ "Was holding M13"
    assert Tracker.interrupted(id) == nil
  end

  test "not once the mount has been switched on since: its counts moved on", %{id: id} do
    held(id, DateTime.add(DateTime.utc_now(), -600))
    Settings.put("mount_power_on", Map.put(Settings.get("mount_power_on", %{}), id, System.os_time(:millisecond)))
    assert Tracker.interrupted(id) == nil
  after
    Settings.put("mount_power_on", Map.delete(Settings.get("mount_power_on", %{}), id))
  end
end
