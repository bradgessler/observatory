defmodule Controller.AlignWithCameraTest do
  @moduledoc """
  The Alignment page's quickest way through the Stars step (#111): with the
  Sony on the telescope, one key, Align with the Camera. Without a camera the
  key is there, greyed, with one line saying what it needs.

  A camera alignment needs no home, so with a camera on (or an alignment
  already made without one) the page does not stop at Set Home: it is
  offered, marked optional. On such a mount the one thing left is which
  side the counterweight is on, asked right under the camera's card, and
  the page moves on to Look once it is answered (#113).
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{AutoAlign, StillCamera}
  alias Controller.Sky.{Lineup, Tracker}
  alias Controller.Test.KnownMount

  setup tags do
    id = "sim-awc-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    unless tags[:no_home], do: :ok = Mount.set_home(id)
    Lineup.clear(id)
    on_exit(fn -> AutoAlign.stop(id); Lineup.clear(id) end)
    %{id: id}
  end

  defp no_camera! do
    # a camera from the test before is noticed gone within the stills camera's look (3 s)
    assert Enum.find(1..80, fn _ -> AutoAlign.camera() == nil or (Process.sleep(100) && false) end), "a camera is still listed: #{inspect(AutoAlign.camera())}"
  end

  defp sony! do
    cam = "sim-still-awc-#{System.unique_integer([:positive])}"
    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}})
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    cam
  end

  defp step(view), do: view |> element(~s(.flow-steps li[aria-current="step"])) |> render() |> LazyHTML.from_fragment() |> LazyHTML.text()

  test "no camera: the key is greyed and the page says what it needs", %{conn: conn, id: id} do
    no_camera!()
    {:ok, view, html} = live(conn, "/alignment/#{id}")
    assert html =~ "Align with the Camera"
    assert html =~ "Put the Sony on the telescope and turn it on in PC Remote"
    assert has_element?(view, ~s(button[phx-click="camera_align"][disabled]))
  end

  test "with the Sony on: one tap starts it, from home it points up high first, and it can be stopped", %{conn: conn, id: id} do
    sony!()
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

  # 8 October: the Sony on and ready, and the Telescope Camera page said to plug a camera in
  test "the Telescope Camera page with only the Sony on says where it is, not to plug one in", %{conn: conn} do
    no_camera!()
    {:ok, view, html} = live(conn, ~p"/cameras/telescope")
    assert html =~ "plug the telescope camera into the box"

    sony!()
    html = render(view)
    assert html =~ "No telescope camera."
    assert html =~ "is ready on"
    assert has_element?(view, ~s(a[href="/cameras/stills"]), "Stills Camera")
    refute html =~ "plug the telescope camera into the box"
  end

  @tag :no_home
  test "no home, no camera, nothing aligned: Set Home is the step, as before", %{conn: conn, id: id} do
    no_camera!()
    {:ok, view, html} = live(conn, "/alignment/#{id}")
    assert step(view) =~ "Set Home"
    assert html =~ "First: Set Home"
    refute html =~ "(optional)"
  end

  @tag :no_home
  test "no home, the Sony on: straight to the camera, Set Home offered as optional, and one tap starts it from where it points", %{conn: conn, id: id} do
    sony!()
    AutoAlign.subscribe()
    {:ok, view, html} = live(conn, "/alignment/#{id}")

    assert step(view) =~ "Stars"
    # not done, not in the way: no ✓, and it says it's optional
    assert has_element?(view, ".flow-steps li.later", "Set Home (optional)")
    refute has_element?(view, ".flow-steps li.done", "Set Home")
    assert has_element?(view, ~s{button[phx-click="camera_align"]:not([disabled])})
    assert html =~ "no home needed"
    assert html =~ "Set Home, If You Like"
    refute html =~ "First: Set Home"
    # Align by Stars still needs home; the phone at the eyepiece is named as such
    assert html =~ "Align by Phone Photo"
    assert html =~ "Your phone held to the eyepiece"

    # never zeroed, a Dec of 0 is only where it was switched on: it takes pictures from here, no Go To first
    view |> element(~s(button[phx-click="camera_align"])) |> render_click()
    assert_receive {:auto_align, ^id, %{done: false, camera: :still}}, 5_000
    refute render(view) =~ "Couldn't point it up high"
    refute render(view) =~ "Pointing up high"

    view |> element(~s(button[phx-click="camera_align_stop"])) |> render_click()
    assert %{done: true, words: "Stopped"} = AutoAlign.status(id)
  after
    Mount.stop(id)
  end

  # The night of 8 October: aligned by the camera with no home, the side guessed upside down.
  @tag :no_home
  test "no home, aligned without one: the counterweight question is right under the camera's card, and the answer moves it on to Look", %{conn: conn, id: id} do
    no_camera!()
    KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])
    status = Lineup.status(id)
    assert status.n == 4 and "just look" in status.good_for
    assert status.counterweight == :guessed

    {:ok, view, html} = live(conn, "/alignment/#{id}")
    # aligned well enough to look, but Go To waits for the side: not Look yet, and no Go To keys
    assert step(view) =~ "Stars"
    assert html =~ "Align with the Camera"
    assert html =~ "Is the counterweight below or above level right now?"
    assert has_element?(view, ~s(#counterweight [role="radio"]), "Below Level")
    refute has_element?(view, ~s(button[phx-click="go"]))
    # the card sits right under the camera's
    assert html |> String.split("Align with the Camera") |> List.last() |> String.split(~s(id="counterweight")) |> length() == 2

    html = view |> element(~s(#counterweight [role="radio"]), "Below Level") |> render_click()
    assert html =~ "Told: the counterweight is below level right now"
    assert Lineup.status(id).counterweight == :told
    assert step(view) =~ "Look"
    refute has_element?(view, "#counterweight")

    # and Go To goes from the list (a flip asks on the object's page; neither waits for the side)
    case Regex.run(~r/phx-click="go" phx-value-id="([^"]+)"/, render(view)) do
      [_, oid] ->
        html = render_click(view, "go", %{"id" => oid})
        refute html =~ "Which side is the counterweight on?"
        assert html =~ "Going to" or html =~ "meridian flip"

      nil ->
        assert render(view) =~ "Nothing up right now"
    end
  after
    Tracker.stop(id)
    Mount.stop(id)
  end
end
