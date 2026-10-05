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
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Sky.Lineup
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

    for path <- ["/object/m13?mount=#{id}", "/alignment/#{id}"] do
      {:ok, _view, html} = live(conn, path)
      assert html =~ "Counterweight side: guessed.", path
      assert html =~ link, path
    end

    # the alignment status says it too: the Alignment pages' toolbar, and the sidebar's line on every page
    conn = Plug.Test.init_test_session(conn, %{"telescope" => id})
    {:ok, status, html} = live(conn, "/alignment/#{id}")
    assert html =~ "Counterweight side guessed. Tell it on Setup"
    assert has_element?(status, ".al-chip .tone-caution", "Counterweight side guessed")

    {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    refute render(status) =~ "Counterweight side: guessed."
    # (the watcher hears the alignment change and tells every page's sidebar)
    Process.sleep(300)
    refute render(status) =~ "Counterweight side guessed"

    {:ok, _view, html} = live(conn, "/object/m13?mount=#{id}")
    refute html =~ "Counterweight side: guessed."
  end
end
