defmodule Controller.ScopeCameraFocusLiveTest do
  @moduledoc """
  Focusing by hand: turn the focuser and watch; every picture is a sample,
  and the page says one thing to do next.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.ScopeCamera

  setup do
    id = "sim-focus-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    ScopeCamera.simulate(true)

    on_exit(fn ->
      ScopeCamera.live(false)
      ScopeCamera.simulate(false)
      Controller.Settings.put("sim_defocus", 0.0)
    end)

    :ok
  end

  defp eventually(view, text, tries \\ 100) do
    html = render(view)

    cond do
      html =~ text -> html
      tries == 0 -> flunk("never saw #{inspect(text)}")
      true ->
        if rem(tries, 40) == 0, do: IO.puts("SAW " <> inspect(Regex.run(~r/focus-advice[^>]*>([^<]*)/, html, capture: :all_but_first)))
        Process.sleep(100)
        eventually(view, text, tries - 1)
    end
  end

  test "every picture is a sample: sharper, past the sharpest, and the picture shows what was ignored", %{conn: conn} do
    # start blurred, from a clean slate
    Controller.Settings.put("sim_defocus", 1.5)
    {:ok, view, html} = live(conn, ~p"/cameras/telescope/focus")
    assert html =~ "Turn the focuser slowly"
    Process.sleep(1_500)
    render_click(view, "start_over")
    eventually(view, "Nothing in the picture is getting sharper")

    # then sharp: getting sharper, or at the sharpest
    Controller.Settings.put("sim_defocus", 0.0)
    eventually(view, ~r/Getting sharper|At the sharpest so far/, 200)
    # past it: blurred again for a while
    Controller.Settings.put("sim_defocus", 1.5)
    html = eventually(view, "passed the sharpest point", 300)
    assert html =~ "Turn back a little"
    # the overlay: stars ringed, the border drawn, a legend in words, the line, the pulse; nothing to press
    assert html =~ ~s(class="ov-border")
    assert html =~ "Speck, ignored: a hot pixel or noise"
    assert html =~ ~s(class="spark focus-spark")
    assert html =~ ~s(class="focus-pulse")
    assert html =~ "a step shows up about"
    refute html =~ "Stepped In"
  end

  test "while the telescope moves, readings pause and the line leaves a shaded gap", %{conn: conn} do
    {:ok, view, _html} = live(conn, ~p"/cameras/telescope/focus")
    id = Enum.find(Mount.local_list(), &String.starts_with?(&1.id, "sim-focus-")).id
    Mount.slew(id, :ra, 64)
    html = eventually(view, "Readings pause until it stops", 100)
    assert html =~ "telescope is moving"
    Mount.stop(id)
  end

  test "the latency is the light of a picture taken after the step, the measuring, and the trip; worst, one more exposure" do
    assert Controller.ScopeCameraFocusLive.latency(%{exposure_ms: 500, stack: 1, measure_ms: 500}) == {1200, 1700}
    assert Controller.ScopeCameraFocusLive.latency(%{exposure_ms: 1000, stack: 4, measure_ms: 400}) == {4600, 5600}
  end

  test "the camera page is the picture and what to do with it; the knobs are a page away", %{conn: conn} do
    {:ok, _view, html} = live(conn, ~p"/cameras/telescope")
    assert html =~ ~s(href="/cameras/telescope/focus")
    assert html =~ "Live View" and html =~ "Find Where It&#39;s Pointing"
    assert html =~ ~s(href="/cameras/telescope/settings")
    # not here any more
    refute html =~ "Half-flux radius"
    refute html =~ "Keep Frames"
    refute html =~ "Exposures Per Frame"

    {:ok, view, html} = live(conn, ~p"/cameras/telescope/settings")
    assert html =~ "Exposure" and html =~ "Gain" and html =~ "Exposures Per Frame" and html =~ "Keep Frames"
    before = ScopeCamera.status().settings["exposure_ms"]
    render_click(view, "set", %{"exposure_ms" => "250"})
    assert ScopeCamera.status().settings["exposure_ms"] == 250
    ScopeCamera.set(exposure_ms: before)
  end
end
