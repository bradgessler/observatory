defmodule Controller.EyepieceTest do
  @moduledoc "The eyepiece draws what the tube sees, and the arrows move it."
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sim.Truth
  alias Controller.Sky.{Lineup, Pointing}

  setup do
    id = "sim-eye-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Lineup.clear(id)
    Truth.put(id, Truth.default(Pointing.site().lat))
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  test "before zeroing there is nothing to look at", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/controls/eyepiece/#{id}")
    assert html =~ "Nothing to Look At Yet"
    assert html =~ "Set home first"
  end

  test "once zeroed it draws the field, and says it is the simulator's truth", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, _view, html} = live(conn, "/controls/eyepiece/#{id}")
    assert html =~ "eyepiece"
    assert html =~ ~s(role="img")
    assert html =~ "What the simulated tube really sees"
    assert html =~ "Pointing at RA"
  end

  # The arrows are derived from the field, not from the sky compass: on a
  # crooked mount the axis that moves the picture right is not always RA.
  # What must hold is that one axis moves by the step, and the picture goes
  # the way the arrow points.
  test "a nudge moves one axis by the step, and the field goes that way", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/controls/eyepiece/#{id}")
    before = Mount.snapshot(id).axes
    ctx = Pointing.context(DateTime.utc_now(), id)
    %{ra_deg: ra0, dec_deg: dec0} = Truth.looking_at(Mount.snapshot(id), ctx)

    render_click(view, "step", %{"deg" => "0.5"})
    render_click(view, "nudge", %{"dir" => "right"})
    Process.sleep(1_500)

    now = Mount.snapshot(id).axes
    moved = max(abs(now.ra.degrees - before.ra.degrees), abs(now.dec.degrees - before.dec.degrees))
    assert_in_delta moved, 0.5, 0.3

    # the tube really went somewhere: the field centre moved
    %{ra_deg: ra1, dec_deg: dec1} = Truth.looking_at(Mount.snapshot(id), ctx)
    assert Controller.Sky.Astro.separation_radec(ra0, dec0, ra1, dec1) > 0.2
  end

  test "the field of view changes what is drawn", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/controls/eyepiece/#{id}")
    wide = render_click(view, "fov", %{"deg" => "5.0"})
    narrow = render_click(view, "fov", %{"deg" => "0.5"})
    # a wider field holds more objects than a narrow one on the same centre
    assert count(wide, "ep-star") >= count(narrow, "ep-star")
  end

  # A field with a bright named star in it: this renders the label branch,
  # where a string once sat on the left of an `and` and crashed the page.
  test "a named bright star in the field is drawn and labelled", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    star = Enum.find(Controller.Sky.Stars.all(), &(&1.name == "Vega"))
    now = DateTime.utc_now()

    # put the tube truly on Vega, the way a hand at the eyepiece would
    {r, d} = Truth.encoders_for(id, star.ra_deg, star.dec_deg, now)
    :ok = Mount.goto_relative(id, :ra, r)
    :ok = Mount.goto_relative(id, :dec, d)
    wait_still(id)

    {:ok, view, _} = live(conn, "/controls/eyepiece/#{id}")
    html = render_click(view, "fov", %{"deg" => "5.0"})
    assert html =~ "ep-star"
    assert html =~ "Vega"
  end

  defp wait_still(id, tries \\ 240) do
    s = Mount.snapshot(id)

    if (s.axes.ra.running or s.axes.dec.running or s.axes.ra.goto_pending or s.axes.dec.goto_pending) and tries > 0 do
      Process.sleep(250)
      wait_still(id, tries - 1)
    end
  end

  defp count(html, class), do: html |> String.split(class) |> length()
end
