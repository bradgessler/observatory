defmodule Controller.CounterweightTest do
  @moduledoc """
  Which side the counterweight is on is asked, not assumed (#113). A German
  equatorial mount sees the same sky from either side, so an alignment only
  guesses it, and on the night every plate was taken with the counterweight
  bar near level the guess was upside down: Go To wanted to flip to the
  unsafe pose. A mount with no home now asks, where it gets its alignment
  and on Setup, in words someone standing at it can answer by looking; the
  answer is kept with the alignment and shown as a fact that can be changed;
  and while it is still a guess, every page that picks a pose says so.

  On 8 October the guess was upside down again, and a Go To from Tonight's
  List drove the tube to the pose with the counterweight bar 64° above level.
  So on a guess a Go To moves nothing: every page with one says why and asks
  the question right under it, and once told, Go To goes.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.{Astro, Lineup, Pointing, Tracker}
  alias Controller.Test.KnownMount

  @question "Is the counterweight below or above level right now?"
  # plates all taken near the meridian, the bar within 10° of level: the guess comes out upside down
  @near_level [-2.0, 3.0, 5.0, 8.0]

  setup do
    id = "sim-cw-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  defp key(view, label, extra \\ ""), do: element(view, ~s(#counterweight [role="radio"]#{extra}), label)
  @refused "Which side is the counterweight on? Say whether the bar is below or above level right now, then Go To again"
  defp guessed_mode?, do: Enum.any?(Controller.Modes.active(), fn {label, _} -> label == "Counterweight side guessed" end)

  test "Setup asks while the side is a guess; the answer is kept, shown as a fact, and can be changed", %{conn: conn, id: id} do
    # the mount stands 60° east of the meridian, its counterweight well down
    KnownMount.align(id, -60.0, @near_level)
    {:ok, view, html} = live(conn, "/setup/#{id}")

    assert html =~ @question
    assert has_element?(view, "#counterweight .badge", "guessed")
    # two keys in a radio group, 44 px like every segmented control, and neither lit: a guess is not an answer
    assert has_element?(view, ~s(#counterweight .seg[role="radiogroup"]))
    assert has_element?(key(view, "Below Level", ~s([aria-checked="false"])))
    assert has_element?(key(view, "Above Level", ~s([aria-checked="false"])))
    refute has_element?(view, ~s(#counterweight [aria-checked="true"]))
    assert html =~ ~s(href="/docs/setup#counterweight")
    # and it is loud: a mode on every page, and the alignment's own line
    assert guessed_mode?()
    assert Controller.Alignment.summary(id).detail == "Counterweight side guessed. Tell it on Setup"

    html = view |> key("Below Level") |> render_click()
    assert Lineup.status(id).counterweight == :told
    assert html =~ "Told: the counterweight is below level right now"
    # no longer a question: the fact, with the key it was told lit and marked
    refute html =~ @question
    assert html =~ "Below level right now"
    assert has_element?(view, "#counterweight .badge.on", "told")
    assert has_element?(key(view, "Below Level ✓", ~s([aria-checked="true"])))
    assert has_element?(key(view, "Above Level", ~s([aria-checked="false"])))
    refute guessed_mode?()
    refute Controller.Alignment.summary(id).detail =~ "Counterweight"
    below = Lineup.model(id).cw

    # it survives what the alignment survives: more plates, a page opened later
    KnownMount.align(id, -60.0, @near_level ++ [-30.0])
    assert Lineup.model(id).cw == below
    {:ok, view, html} = live(conn, "/setup/#{id}")
    refute html =~ @question
    assert has_element?(key(view, "Below Level ✓", ~s([aria-checked="true"])))

    # and it can be changed, by tapping the other key
    view |> key("Above Level") |> render_click()
    assert Lineup.model(id).cw == -below
    assert has_element?(key(view, "Above Level ✓", ~s([aria-checked="true"])))
    assert render(view) =~ "Above level right now"

    # the page with the question is still one page: no id twice
    ids = Regex.scan(~r/ id="([^"]+)"/, render(view)) |> Enum.map(fn [_, i] -> i end)
    assert ids == Enum.uniq(ids)
  end

  test "with the shaft near level the keys are greyed and one line says what to do", %{conn: conn, id: id} do
    # the mount stands 4° from the meridian: nobody can say below or above by eye
    KnownMount.align(id, 4.0, [-40.0, -30.0, -20.0, -25.0])
    {:ok, view, html} = live(conn, "/setup/#{id}")

    assert html =~ @question
    assert html =~ "The counterweight shaft is close to level right now, too close to call by eye. Turn the RA axis a little, then answer."
    assert has_element?(key(view, "Below Level", "[disabled]"))
    assert has_element?(key(view, "Above Level", "[disabled]"))

    # a tap that gets through anyway (the mount moved after the page was drawn) gets the same calm line
    html = render_click(view, "counterweight", %{"where" => "below"})
    assert html =~ "The counterweight shaft is close to level right now. Turn the RA axis a little and answer again"
    assert Lineup.status(id).counterweight == :guessed
  end

  test "with no alignment nothing is asked, and an answer has nowhere to go", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/setup/#{id}")
    refute html =~ ~s(id="counterweight")
    refute guessed_mode?()
    assert render_click(view, "counterweight", %{"where" => "above"}) =~ "No alignment in force. Add alignment points first, by stars or by photo"
  end

  test "with home set nothing rests on it, so nothing is asked", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    assert guessed_mode?()

    :ok = Mount.set_home(id)
    assert Lineup.status(id).counterweight == nil
    refute guessed_mode?()
    {:ok, _view, html} = live(conn, "/setup/#{id}")
    refute html =~ ~s(id="counterweight")
  end

  test "Align by Photo asks where a mount with no home gets its alignment", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/align/photo/#{id}")
    refute html =~ @question

    # the photos become the alignment (Use This Alignment): the question arrives by itself
    KnownMount.align(id, -60.0, @near_level)
    assert render(view) =~ @question

    html = view |> key("Below Level") |> render_click()
    assert Lineup.status(id).counterweight == :told
    refute html =~ @question
    assert has_element?(key(view, "Below Level ✓", ~s([aria-checked="true"])))
  end

  # Found by the test above: the answer outlives new plates because `Lineup.replace/3` keeps the
  # old model in force while the new one is fitted, and for that moment there is no margin. Every
  # open page asks for the modes just then, and "Star-aligned" crashed on the missing number.
  test "while new points are being fitted, the modes still read", %{id: id} do
    KnownMount.align(id, -60.0, @near_level)
    lineup = Controller.Settings.get("lineup", %{})
    on_exit(fn -> Controller.Settings.put("lineup", lineup) end)
    # only this mount, as `replace` leaves it until its refit lands
    Controller.Settings.put("lineup", %{id => Map.drop(lineup[id], ["rms_arcmin", "worst_arcmin", "residuals_arcmin"])})

    assert {_, detail} = List.keyfind(Controller.Modes.active(), "Star-aligned · 4 stars", 0)
    refute detail =~ "agree"
    assert guessed_mode?()
  end

  test "where a pose is chosen on the guess, the page says so and links to the question", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    link = ~s(href="/setup/#{id}#counterweight")

    {:ok, _view, html} = live(conn, "/object/m13?mount=#{id}")
    assert html =~ "Counterweight side: guessed."
    assert html =~ link

    # the Alignment page, where this alignment was made, asks the question itself (#113)
    {:ok, _view, html} = live(conn, "/alignment/#{id}")
    assert html =~ @question
    assert html =~ ~s(href="/docs/setup#counterweight")

    # the alignment status says it too: the Alignment pages' toolbar, and the sidebar's line on every page
    conn = Plug.Test.init_test_session(conn, %{"telescope" => id})
    {:ok, status, html} = live(conn, "/alignment/#{id}")
    assert html =~ "Counterweight side guessed. Tell it on Setup"
    assert has_element?(status, ".al-chip .tone-caution", "Counterweight side guessed")

    {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    refute render(status) =~ @question
    refute render(status) =~ "Counterweight side: guessed."
    # (the watcher hears the alignment change and tells every page's sidebar)
    Process.sleep(300)
    refute render(status) =~ "Counterweight side guessed"

    {:ok, _view, html} = live(conn, "/object/m13?mount=#{id}")
    refute html =~ "Counterweight side: guessed."
  end

  # -- the guard (#113): on a guess, a Go To moves nothing, and asks right there ------------------

  # a bright star well up and east of the meridian: told the truth (below level, the mount 60° east),
  # a Go To to it stays on this side of the pier
  defp east_star do
    site = Pointing.site()
    lst = Astro.lst_deg(DateTime.utc_now(), site.lon)

    Controller.Sky.Catalog.stars(3.0)
    |> Enum.find(fn s ->
      ha = Astro.hour_angle(lst, s.ra_deg)
      {alt, _} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, lst)
      ha > -70 and ha < -15 and alt > 25
    end)
  end

  defp still!(id, snap) do
    Process.sleep(300)
    now = Mount.snapshot(id)
    refute Enum.any?(now.axes, fn {_, ax} -> ax.running or Map.get(ax, :goto_pending, false) end), "the mount moved on a guess"
    assert now.axes.ra.degrees == snap.axes.ra.degrees
    assert now.axes.dec.degrees == snap.axes.dec.degrees
    refute Tracker.active?(id)
  end

  test "an object's page: Go To on a guess is refused, nothing moves, the question is under Go To; told, Go To goes", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    star = east_star() || flunk("no bright star east of the meridian right now")
    snap = Mount.snapshot(id)

    {:ok, view, _html} = live(conn, "/object/#{star.id}?mount=#{id}")
    refute has_element?(view, "#counterweight")

    html = render_click(view, "slew", %{})
    assert html =~ @refused
    assert has_element?(key(view, "Below Level"))
    assert has_element?(key(view, "Above Level"))
    still!(id, snap)

    # answered right there: the card goes, and the next Go To goes
    html = view |> key("Below Level") |> render_click()
    assert html =~ "Told: the counterweight is below level right now"
    assert Lineup.status(id).counterweight == :told
    refute has_element?(view, "#counterweight")

    html = render_click(view, "slew", %{})
    refute html =~ @refused
    assert html =~ "Going to #{star.name}"
    assert Enum.any?(Mount.snapshot(id).axes, fn {_, ax} -> ax.running or Map.get(ax, :goto_pending, false) end)
  after
    Tracker.stop(id)
    Mount.stop(id)
  end

  test "Tonight: Go To on a guess is refused beside the list, nothing moves, the question is under it; told, Go To goes", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    star = east_star() || flunk("no bright star east of the meridian right now")
    snap = Mount.snapshot(id)

    {:ok, view, _html} = live(conn, "/tonight/#{id}")
    render_click(view, "pick", %{"id" => star.id})
    html = render_click(view, "goto", %{})
    assert html =~ @refused
    assert has_element?(view, ".pick-panel #counterweight")
    assert has_element?(key(view, "Below Level"))
    still!(id, snap)

    view |> key("Below Level") |> render_click()
    assert Lineup.status(id).counterweight == :told
    refute has_element?(view, "#counterweight")

    html = render_click(view, "goto", %{})
    refute html =~ @refused
    assert html =~ "Going to #{star.name}"
  after
    Tracker.stop(id)
    Mount.stop(id)
  end

  test "the Eyepiece page: its Go To to the next star waits the same way, with the question under it", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    snap = Mount.snapshot(id)

    {:ok, view, _html} = live(conn, "/controls/eyepiece/#{id}")
    html = render_click(view, "slew", %{})
    assert html =~ "Which side is the counterweight on?"
    assert has_element?(key(view, "Below Level"))
    still!(id, snap)

    view |> key("Below Level") |> render_click()
    assert Lineup.status(id).counterweight == :told
    refute has_element?(view, "#counterweight")
  after
    Tracker.stop(id)
    Mount.stop(id)
  end

  test "a hold the box went down in the middle of, offered back on a guess, opens its page with the question", %{conn: conn, id: id} do
    KnownMount.align(id, -60.0, @near_level)
    held = %{"target" => %{"id" => "m13", "name" => "M13", "ra_deg" => 250.42, "dec_deg" => 36.46}, "since" => DateTime.to_iso8601(DateTime.utc_now())}
    Controller.Settings.put("hold", Map.put(Controller.Settings.get("hold", %{}), id, held))
    on_exit(fn -> Controller.Settings.put("hold", Map.delete(Controller.Settings.get("hold", %{}), id)) end)

    {:ok, view, _html} = live(conn, "/")
    assert {:error, {:live_redirect, %{to: to}}} = render_click(view, "resume", %{"id" => id})
    assert to =~ "/object/m13"
    assert to =~ "ask=counterweight"

    {:ok, view, _html} = live(conn, to)
    assert has_element?(key(view, "Below Level"))
    refute Tracker.active?(id)
  end
end
