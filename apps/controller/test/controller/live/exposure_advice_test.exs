defmodule Controller.ExposureAdviceTest do
  @moduledoc """
  The starting exposure for a target (`Controller.Sky.Exposure`, #117), where
  it is shown: on the object's own page under what the object is, and beside
  Tonight's List on a wide screen. One line and its reason, advice only; the
  key that sets it is on the camera's Exposure screen (still_camera_test.exs).
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Settings

  setup do
    id = "sim-exposure-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000

    # the 8SE as the box knows it: its aperture, and the focal length a plate solve measured
    was = {Settings.get("aperture_mm"), Settings.get("focal_length_mm")}
    Settings.put("aperture_mm", 203.2)
    Settings.put("focal_length_mm", 2084)

    on_exit(fn ->
      # never nil: Settings has no delete, and a nil left behind takes the place of the pages' default of 100
      Settings.put("aperture_mm", elem(was, 0) || 100)
      Settings.put("focal_length_mm", elem(was, 1))
    end)

    %{id: id}
  end

  test "a planet's page: ISO and shutter from its surface brightness at this telescope's f-ratio", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/object/sol-saturn?mount=#{id}")
    assert html =~ "Start at ISO 800 · 1/60 s"
    assert html =~ "From the surface brightness of Saturn, 6.8 mag per square arcsecond, at f/10.3."
    # one line over its reason, with the way to what it is based on
    assert has_element?(view, ~s(.exposure-advice .setting-text strong), "Start at ISO 800 · 1/60 s")
    assert has_element?(view, ~s(.exposure-advice a.help[href="/docs/still-camera#suggested-exposure"][aria-label="help: the suggested exposure"]))
    refute html =~ "—"
  end

  test "a galaxy's page: the longest untrailed shutter, a high ISO and frames to stack", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/object/m31?mount=#{id}")
    assert html =~ "Start at ISO 3200 · 15 s · 20 frames"
    assert html =~ "Sky glow and tracking set this, not its magnitude."
  end

  test "the telescope's optics change: the page's suggestion follows", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/object/sol-saturn?mount=#{id}")
    assert html =~ "at f/10.3."
    # a reducer: the same aperture at half the focal length
    Settings.put("focal_length_mm", 1042)
    assert render(view) =~ "at f/5.1."
  end

  test "with the optics not set it assumes f/10 and says so", %{conn: conn, id: id} do
    Settings.put("focal_length_mm", nil)
    {:ok, _view, html} = live(conn, "/object/sol-saturn?mount=#{id}")
    assert html =~ "Assumes f/10: the telescope&#39;s aperture and focal length are not both set."
  end

  test "Tonight: a picked target's panel carries the suggestion under what it is", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/tonight/#{id}")
    refute html =~ "pick-exposure"

    html = render_click(view, "pick", %{"id" => "m57"})
    # a line of the panel that only a wide screen shows (.pick-about)
    assert html =~ ~r|<p class="pick-about pick-exposure">Start at ISO 1600 · 15 s · 8 frames\. The longest shutter under the 15 s default tracking limit|

    html = render_click(view, "pick", %{"id" => "sol-jupiter"})
    assert html =~ ~r|<p class="pick-about pick-exposure">Start at ISO 800 · 1/250 s\. From the surface brightness of Jupiter|

    refute render_click(view, "clear", %{}) =~ "pick-exposure"
  end

  test "the docs say what the suggestion is based on, where the pages' ? lands", %{conn: conn} do
    html = conn |> get("/docs/still-camera") |> html_response(200)
    assert html =~ ~s(id="suggested-exposure")
    assert html =~ "It is advice"
  end
end
