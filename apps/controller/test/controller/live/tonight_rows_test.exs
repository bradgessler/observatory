defmodule Controller.TonightRowsTest do
  @moduledoc """
  A row of the Tonight list is the same columns in every row, in the same
  order: the number (or kind), the name over its detail, how long it's up,
  and how high, drawn, last. The night the list came out jagged, the drawn
  angle sat before the "until", and what Go To would do sat under that, so
  every row's angle was wherever those words left it. Then what Go To and
  the hold would do became words on the detail line ("Tracks to 1:26, then
  flip"), and on 8 October that was noise on a list: a row is what it is,
  where, and until when. What Go To and tracking will do for one target is
  on its own page. (The tracks the columns sit in are checked from the
  stylesheet, in design_test.exs.)
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.Lineup

  setup do
    id = "sim-rows-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  # the columns of a row that is up, and of one that isn't yet (nothing to draw in the last)
  @up ~w(k t when height)
  @later ~w(k t when)

  test "not aligned: every row is number, name over detail, until, angle; none says what Go To will do", %{conn: conn, id: id} do
    {:ok, _view, html} = live(conn, "/tonight/#{id}")
    {up, later} = rows(html)

    assert up != []
    assert_columns(up, later)
    assert Enum.all?(up ++ later, &(&1.reach == []))
    assert html =~ "Not aligned yet"
  end

  test "home set: the same columns, and no row says what Go To and tracking will do", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    assert Mount.snapshot(id).homed

    {:ok, _view, html} = live(conn, "/tonight/#{id}")
    {up, later} = rows(html)

    assert up != []
    assert_columns(up, later)
    assert Enum.all?(up ++ later, &(&1.reach == [])), "a row with what Go To will do: #{inspect(Enum.flat_map(up, & &1.reach))}"
    refute html =~ "Tracks to"
    refute html =~ "Not aligned yet"
  end

  test "star-aligned, where a Go To may have to flip the mount: the same columns again", %{conn: conn, id: id} do
    now = DateTime.utc_now()

    Lineup.replace(
      id,
      [point("Vega", 279.23, 38.78, 10.0, 40.0, now), point("Altair", 297.70, 8.87, 30.0, 70.0, now), point("Deneb", 310.36, 45.28, 20.0, 30.0, now)],
      nil
    )

    assert Lineup.model(id)

    {:ok, _view, html} = live(conn, "/tonight/#{id}")
    {up, later} = rows(html)

    assert up != []
    assert_columns(up, later)
    assert Enum.all?(up ++ later, &(&1.reach == []))
    refute html =~ "then flip"
  end

  # The "until" is said in the viewer's clock as soon as their browser gives its offset.
  test "once the viewer's clock is known, a row's time is in it", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, view, html} = live(conn, "/tonight/#{id}")
    {up, later} = rows(html)
    assert Enum.any?(up ++ later, &(&1.when =~ "UTC")), "no row with a time: nothing to check"

    {up, later} = view |> render_hook("clock", %{"offset_min" => -420}) |> rows()
    for row <- up ++ later, do: refute(row.when =~ "UTC", "#{row.name}: #{row.when}")
  end

  # -- the rows as they are rendered ---------------------------------------------------

  # {rows that are up, rows that rise later}: each row's tag, name, columns (the first class
  # of each child, in order), its "until" and what it says Go To will do
  defp rows(html) do
    doc = LazyHTML.from_fragment(html)
    {for(row <- LazyHTML.query(doc, ".targets:not(.later) .target"), do: row(row)), for(row <- LazyHTML.query(doc, ".targets.later .target"), do: row(row))}
  end

  defp row(node) do
    [{tag, _attrs, children}] = LazyHTML.to_tree(node)

    %{
      tag: tag,
      name: node |> LazyHTML.query(".t > strong") |> LazyHTML.text(),
      columns: for({_, attrs, _} <- children, do: attrs |> class() |> String.split() |> hd()),
      when: node |> LazyHTML.query(".when") |> LazyHTML.text() |> String.trim(),
      # only ever inside the detail: a row has no column for it
      reach: for(r <- LazyHTML.query(node, ".t > .d > .reach-short"), do: r |> LazyHTML.text() |> String.trim()),
      stray: Enum.count(LazyHTML.query(node, ".reach-short")) - Enum.count(LazyHTML.query(node, ".t > .d > .reach-short"))
    }
  end

  defp class(attrs), do: Enum.find_value(attrs, "", fn {k, v} -> k == "class" && v end)

  # a phone's row is a link, a wide screen's a key with the chevron that marks the picked one after its columns
  defp assert_columns(up, later) do
    for {rows, columns} <- [{up, @up}, {later, @later}], row <- rows do
      want = if row.tag == "button", do: columns ++ ["pick-arrow"], else: columns
      assert row.columns == want, "#{row.name} (#{row.tag}): #{inspect(row.columns)}"
      assert row.stray == 0, "#{row.name}: what Go To will do belongs on the detail line"
      assert row.when != ""
    end

    # both forms of every row
    assert Enum.count(up, &(&1.tag == "a")) == Enum.count(up, &(&1.tag == "button"))
  end

  defp point(name, ra, dec, tr, td, at),
    do: %{"name" => name, "at" => DateTime.to_iso8601(at), "theta_ra" => tr, "theta_dec" => td, "ra_deg" => ra, "dec_deg" => dec}
end
