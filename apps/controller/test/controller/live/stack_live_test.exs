defmodule Controller.StackLiveTest do
  @moduledoc """
  The Control Stack: every layer in plain words, the layers an input works
  through marked, the hold's error recomputed from the motors, and every row
  a tap away from its own live page.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Stack

  setup do
    id = "sim-stack-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  @model %{axis_low: 3.34, axis_west: 5.49, off_pole: 5.55, off_ra: 299.74, off_dec: 132.89, n: 8, rms: 6.8}

  defp hold(id, extra \\ %{}) do
    Stack.note(id, Map.merge(%{law: 5, source: "the hold", action: :hold, target: %{name: "Saturn", ra_deg: 11.77, dec_deg: 2.11}, model: @model}, extra))
  end

  test "every layer is there in plain words, and nobody driving says so", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/stack/#{id}")
    for {_law, name, _} <- Stack.layers(:gem), do: assert(html =~ name |> Phoenix.HTML.html_escape() |> Phoenix.HTML.safe_to_string())
    assert html =~ "Nobody is driving"
    assert html =~ "not measured"
    assert html =~ "no alignment yet"
  end

  test "a pull on the touchpad marks the layers it works through and shows the translation", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/stack/#{id}")
    Stack.note(id, %{law: 1, source: "Center touchpad", view: {0.0, 1.0}, speed: 2.8, rates: [ra: -1.8]})
    html = render(view)
    assert html =~ "Center touchpad is driving: view up at 2.8× → RA −1.8×"
    assert html =~ "working now"
  end

  test "the hold reports what it holds and the geometry it uses", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/stack/#{id}")
    hold(id)
    html = render(view)
    assert html =~ "Tracking Saturn"
    assert html =~ "from the pole"
    assert html =~ "8 points, ±14′"
  end

  test "a page opened later starts from the last word of each layer", %{conn: conn, id: id} do
    hold(id)
    Process.sleep(100)
    {:ok, _view, html} = live(conn, "/stack/#{id}")
    assert html =~ "Tracking Saturn"
    assert html =~ "8 points, ±14′"
  end

  test "a row taps into its own live page: what it is, where the number comes from, what to do", %{conn: conn, id: id} do
    hold(id)
    Process.sleep(100)
    {:ok, view, _} = live(conn, "/stack/#{id}")
    html = view |> element(~s(a[href="/stack/#{id}/tripod"])) |> render_click()
    assert html =~ "Tripod tilt"
    assert html =~ "North–south"
    assert html =~ "What It Is"
    assert html =~ "a level reading"

    {:ok, _view, html} = live(conn, "/stack/#{id}/polar")
    assert html =~ "3.34°"
    assert html =~ "Where the Number Comes From"
  end
end
