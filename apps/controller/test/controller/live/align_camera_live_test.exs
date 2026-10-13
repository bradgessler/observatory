defmodule Controller.AlignCameraLiveTest do
  @moduledoc """
  Align with the Camera as a page of its own, step by step (12 October 2026).
  The run had been one card inside the Alignment page: hard to find, silent
  about what the solver was doing, and after a failed run there was no way to
  tell that it had failed.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{AutoAlign, StillCamera}
  alias Controller.Sky.{Lineup, Tracker}
  alias Controller.Test.KnownMount

  setup do
    id = "sim-acl-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Lineup.clear(id)
    on_exit(fn -> AutoAlign.stop(id); Lineup.clear(id) end)
    %{id: id}
  end

  defp no_camera! do
    assert Enum.find(1..80, fn _ -> AutoAlign.camera() == nil or (Process.sleep(100) && false) end), "a camera is still listed: #{inspect(AutoAlign.camera())}"
  end

  defp sony! do
    cam = "sim-still-acl-#{System.unique_integer([:positive])}"
    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}})
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    cam
  end

  defp step(view), do: view |> element(~s(.flow-steps li[aria-current="step"])) |> render() |> LazyHTML.from_fragment() |> LazyHTML.text()

  test "it is a page under Alignment, listed with the other ways to align" do
    # the group is Alignment, so its pages are named by what does the aligning: Camera, Stars, Phone
    page = Enum.find(Controller.Nav.pages(), &(&1.path == "/align/camera"))
    assert page.title == "Camera"
    assert page.path == "/align/camera"
    {group, _, pages} = Enum.find(Controller.Nav.groups(), fn {_, _, pages} -> page in pages end)
    assert group == "Alignment"
    titles = Enum.map(pages, & &1.title)
    assert titles == ["Camera", "Stars", "Phone"]
  end

  test "no camera: it says so, the key is greyed, and it points to the two other ways", %{conn: conn, id: id} do
    no_camera!()
    {:ok, view, html} = live(conn, "/align/camera/#{id}")
    assert step(view) =~ "Camera"
    assert html =~ "No camera on the telescope"
    assert has_element?(view, ~s(button[phx-click="start"][disabled]))
    assert has_element?(view, ~s(a[href="/align/photo/#{id}"]))
    assert has_element?(view, ~s(a[href="/controls/align/#{id}"]))
  end

  test "the camera on: its state, a test picture with how long ago it was taken, and one key starts the run", %{conn: conn, id: id} do
    sony!()
    AutoAlign.subscribe()
    {:ok, view, html} = live(conn, "/align/camera/#{id}")
    assert step(view) =~ "Camera"
    assert html =~ ": ready"
    assert has_element?(view, ~s{button[phx-click="start"]:not([disabled])})

    # a test picture: the latest picture is shown, with its age in words
    view |> element(~s(button[phx-click="test_picture"])) |> render_click()
    assert_receive {:still_camera, %{last: %{seq: _, w: _}}}, 20_000
    # (the page hears of the picture as this test does: look once it has drawn it)
    # (a picture left by a test before this one may be on the page first, minutes old)
    fresh? = fn h -> h =~ "Taken just now" or h =~ ~r/Taken \d+ s ago/ end
    html = Enum.find_value(1..60, fn _ -> (h = render(view)) |> fresh?.() && h || (Process.sleep(50) && nil) end)
    assert html, "the page never showed the new picture's age"
    assert has_element?(view, ~s(.scope-frame img[src^="/cameras/stills/latest.png"]))

    view |> element(~s(button[phx-click="start"])) |> render_click()
    assert_receive {:auto_align, ^id, %{done: false, camera: :still}}, 5_000
    assert step(view) =~ "Pictures"
    assert render(view) =~ "of 4 solved"
    assert has_element?(view, ~s(button[phx-click="stop_aligning"]))

    view |> element(~s(button[phx-click="stop_aligning"])) |> render_click()
    assert %{done: true, ok: false} = AutoAlign.status(id)
    # back at the camera, and it says the run did not get there
    assert step(view) =~ "Camera"
    assert render(view) =~ "Not aligned: Stopped."
    assert has_element?(view, ~s(button[phx-click="start"]), "Start Again")
  after
    Mount.stop(id)
  end

  # what the queue says about each picture is on the page as it happens: the stage, the time used
  # of the time allowed, and how it ended
  test "every picture is a row that says where its solve is", %{conn: conn, id: id} do
    {:ok, view, _html} = live(conn, "/align/camera/#{id}")
    now = System.system_time(:millisecond)

    plates = [
      %{n: 1, state: :solved, moving: false, reason: nil, solution: %{ra_deg: 1.0, dec_deg: 2.0, seconds: 9.4, stars: 36}, solving: nil},
      %{n: 2, state: :failed, moving: false, reason: "too_few_stars", solution: nil, solving: nil},
      %{n: 3, state: :solving, moving: false, reason: nil, solution: nil,
        solving: %{stage: :matching, how: :blind, stars: 48, limit_ms: 110_000, since_ms: now - 14_000, stage_ms: now - 12_000, total_ms: 120_000}}
    ]

    send(view.pid, {:auto_align, id, %{done: false, ok: nil, phase: :shooting, words: "Taking picture 3, then plate solving it", picture: 3, solved: 1, enough: 4, camera: :still}})
    send(view.pid, {:plates, id, %{mount: id, session: "s", plates: plates, report: nil, applied: false, home_at: nil, workers: 1, fitting: false, fit_notice: nil}})
    html = render(view)

    assert step(view) =~ "Pictures"
    assert html =~ "1 of 4 solved"
    assert html =~ "Solved · in 9 s · 36 stars"
    assert html =~ "No match: too few stars"
    assert html =~ "48 stars. Matching against the whole sky"
    assert html =~ ~r/1[4-6] s of up to 120/, "the time used: #{inspect(Regex.run(~r/\d+ s of up to \d+/, html))}"
    assert has_element?(view, ~s(progress[max="120"]))

    # handed over: one instruction and one key
    send(view.pid, {:auto_align, id, %{done: false, ok: nil, phase: :waiting, words: "Three pictures in a row found no match. Move the telescope to open sky, then tap Continue", picture: 5, solved: 1, enough: 4, camera: :still}})
    assert has_element?(view, ~s(.align-now[role="status"]), "Move the telescope to open sky, then tap Continue")
    assert has_element?(view, ~s(button[phx-click="continue"]))
  end

  test "aligned on a mount with no home: the counterweight question, then Look", %{conn: conn, id: id} do
    no_camera!()
    KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])
    assert Lineup.status(id).counterweight == :guessed

    {:ok, view, html} = live(conn, "/align/camera/#{id}")
    assert step(view) =~ "Counterweight"
    assert html =~ "Aligned: 4 points agree"
    assert html =~ "Is the counterweight below or above level right now?"

    view |> element(~s(#counterweight [role="radio"]), "Below Level") |> render_click()
    assert Lineup.status(id).counterweight == :told
    assert step(view) =~ "Look"
    assert has_element?(view, ~s(a[href="/tonight/#{id}"]))
  after
    Tracker.stop(id)
    Mount.stop(id)
  end
end
