defmodule Controller.AlignWithCameraTest do
  @moduledoc """
  The Alignment page's quickest way through the Stars step (#111): with the
  Sony on the telescope, one key, Align with the Camera. Without a camera the
  key is there, greyed, with one line saying what it needs.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{AutoAlign, StillCamera}
  alias Controller.Sky.Lineup

  setup do
    id = "sim-awc-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    Lineup.clear(id)
    on_exit(fn -> AutoAlign.stop(id); Lineup.clear(id) end)
    %{id: id}
  end

  test "no camera: the key is greyed and the page says what it needs", %{conn: conn, id: id} do
    # a camera from the test before is noticed gone within the stills camera's look (3 s)
    assert Enum.find(1..80, fn _ -> AutoAlign.camera() == nil or (Process.sleep(100) && false) end), "a camera is still listed: #{inspect(AutoAlign.camera())}"
    {:ok, view, html} = live(conn, "/alignment/#{id}")
    assert html =~ "Align with the Camera"
    assert html =~ "Put the Sony on the telescope and turn it on in PC Remote"
    assert has_element?(view, ~s(button[phx-click="camera_align"][disabled]))
  end

  test "with the Sony on: one tap starts it, from home it points up high first, and it can be stopped", %{conn: conn, id: id} do
    cam = "sim-still-awc-#{System.unique_integer([:positive])}"
    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}})
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    AutoAlign.subscribe()

    {:ok, view, _html} = live(conn, "/alignment/#{id}")
    assert has_element?(view, ~s{button[phx-click="camera_align"]:not([disabled])})

    view |> element(~s(button[phx-click="camera_align"])) |> render_click()
    assert_receive {:auto_align, ^id, %{done: false, camera: :still}}, 5_000
    # Set Home leaves the tube on the pole: it goes up high before the first picture
    assert render(view) =~ "Pointing up high" or AutoAlign.status(id).words =~ "frame"
    assert has_element?(view, ~s(button[phx-click="camera_align_stop"]))

    view |> element(~s(button[phx-click="camera_align_stop"])) |> render_click()
    assert %{done: true, ok: false, words: "Stopped"} = AutoAlign.status(id)
    assert render(view) =~ "Stopped"
    Mount.stop(id)
  end
end
