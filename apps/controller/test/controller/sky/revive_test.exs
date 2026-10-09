defmodule Controller.Sky.ReviveTest do
  @moduledoc """
  The hold picks itself up after the box comes back, or after a mount cable
  that dropped comes back (#99): no tap on Home. Only once per cut-off hold,
  and not when the way back is too far to go without someone watching.
  """
  use ExUnit.Case, async: false

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Pointing, Revive, Tracker}
  alias Controller.Test.KnownMount

  setup do
    id = "sim-rv-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    # aligned, as a mount whose hold can be cut off is, with its counterweight side told
    KnownMount.align(id, -60.0, [-30.0, -15.0, 0.0, 15.0])
    {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    Telescope.Events.subscribe()

    on_exit(fn ->
      Tracker.stop(id)
      Lineup.clear(id)
      Settings.put("hold", Map.delete(Settings.get("hold", %{}), id))
    end)

    %{id: id}
  end

  # a hold the box went down in the middle of: the target, `away` degrees in Dec from where the tube points
  defp cut_off(id, away) do
    ctx = Pointing.context(DateTime.utc_now(), id)
    {ra, dec} = Pointing.scope_radec(Mount.snapshot(id), ctx)
    target = %{"id" => nil, "name" => "Test star", "ra_deg" => ra, "dec_deg" => dec - away}
    Settings.put("hold", Map.put(Settings.get("hold", %{}), id, %{"target" => target, "since" => DateTime.to_iso8601(DateTime.utc_now())}))
    assert %{target: %{name: "Test star"}} = Tracker.interrupted(id)
    target
  end

  test "a cut-off hold close by is gone back to and held again, by itself", %{id: id} do
    target = cut_off(id, 2.0)
    start_supervised!({Revive, name: :revive_test, every_ms: 200, clock_wait_ms: 0})

    assert_receive {:event, %{module: :tracker, name: :revived, data: %{id: ^id, target: "Test star"}}}, 5_000
    assert Tracker.interrupted(id) == nil
    assert_eventually(fn -> Tracker.status(id) end, &match?(%{name: "Test star"}, &1), 5_000)

    # and it lands there: the hold's own idea of the target is where the tube now points
    assert_eventually(
      fn ->
        {ra, dec} = Pointing.scope_radec(Mount.snapshot(id), Pointing.context(DateTime.utc_now(), id))
        Astro.separation_radec(ra, dec, target["ra_deg"], target["dec_deg"])
      end,
      &(&1 < 0.1),
      30_000
    )
  end

  test "too far to go back without someone watching: the offer stays on Home, once", %{id: id} do
    cut_off(id, 30.0)
    start_supervised!({Revive, name: :revive_test, every_ms: 200, clock_wait_ms: 0})

    assert_receive {:event, %{module: :tracker, name: :revive_declined, data: %{id: ^id, why: why}}}, 5_000
    assert why =~ "too far"
    refute Mount.snapshot(id).axes.dec.goto_pending
    assert %{target: %{name: "Test star"}} = Tracker.interrupted(id)
    # once per cut-off hold, not every look
    refute_receive {:event, %{module: :tracker, name: :revive_declined, data: %{id: ^id}}}, 1_500
  end

  defp assert_eventually(fun, pred, timeout) do
    deadline = System.monotonic_time(:millisecond) + timeout

    Stream.repeatedly(fn -> fun.() end)
    |> Enum.find(fn v -> pred.(v) or (System.monotonic_time(:millisecond) > deadline and flunk("never: #{inspect(v)}")) or (Process.sleep(200) && false) end)
  end
end
