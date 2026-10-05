defmodule Controller.PagesTest do
  @moduledoc """
  Every page renders against a simulated mount and reacts to the things a
  phone would do. The simulator speaks the real wire protocol, so this is the
  whole stack minus the cable.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-test-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  describe "keypad" do
    test "renders one strip per axis and STOP", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/#{id}")
      assert html =~ "around the polar axis"
      assert html =~ "around the dec axis"
      assert html =~ "STOP"
      # not blended by default
      refute html =~ "as you see it (both motors)"
      assert has_element?(view, "#strip-ra")
    end

    test "a pull on the RA strip slews RA only; letting go stops it", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      render_hook(view, "stick", %{"x" => 1.0, "y" => 0.0, "mag" => 0.6, "axis" => "ra"})
      snap = Mount.snapshot(id)
      assert snap.axes.ra.running
      refute snap.axes.dec.running
      render_hook(view, "stick_end", %{})
      refute Mount.snapshot(id).axes.ra.running
    end

    test "STOP is an instant stop", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      Mount.slew(id, :dec, 64)
      assert Mount.snapshot(id).axes.dec.running
      view |> element("button.stop-bar") |> render_click()
      refute Mount.snapshot(id).axes.dec.running
    end

    test "arrow keys drive the strips without JavaScript", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      render_keydown(view, "keydown", %{"key" => "ArrowRight"})
      assert Mount.snapshot(id).axes.ra.running
      render_keyup(view, "keyup", %{"key" => "ArrowRight"})
      refute Mount.snapshot(id).axes.ra.running
    end
  end

  describe "sky" do
    test "the sky page is the map; Tonight is its own page, both in the sidebar and not linked again", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/sky/#{id}")
      refute html =~ "Tonight ›"
      # the telescope's reach is under the chart; the tree line is the location's, on Location
      assert html =~ "Aperture mm"
      refute html =~ "Tree Line"
      # the Sky's status in the toolbar: the time with its keys, how dark it is, where
      assert html =~ "sky-status"
      assert html =~ ~r/Daylight|Civil twilight|Nautical twilight|Astronomical twilight|Dark/
      assert html =~ ~s(href="/location")
      # a step of the time moves the sky and says by how much; Now brings it back
      assert render_click(view, "shift", %{"by" => "60"}) =~ ~r/class="ss-shift"> \+1 h/
      refute render_click(view, "shift", %{"by" => "now"}) =~ ~s(class="ss-shift")

      # no tree line set in tests: ranked against the real horizon, in two groups
      {:ok, _view, tonight} = live(conn, "/tonight/#{id}")
      assert tonight =~ "Up now, best first"
      refute tonight =~ "Sky Map ›"
      # how high each one is, drawn
      assert tonight =~ ~s(<svg class="height)
    end

    test "a row on Tonight opens the object's page on a phone and shows it beside the list on a wide screen", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/tonight/#{id}")
      assert html =~ "pick-narrow"
      assert html =~ "pick-wide"

      # any object, listed or not: the panel is the same
      html = render_click(view, "pick", %{"id" => "m42"})
      assert html =~ "pick-panel"
      # its path across the sky and its altitude through the night, and the list stays
      assert html =~ ~s(id="pick-path")
      assert html =~ "Its altitude through the night"
      assert html =~ "Up now, best first" or html =~ "Rising later" or html =~ "Nothing above"
      assert html =~ "Details ›"

      refute render_click(view, "clear", %{}) =~ "pick-panel"
    end

    test "slewing before home explains itself", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/sky/#{id}")
      render_click(view, "pick", %{"id" => "m13"})
      assert render_click(view, "goto", %{}) =~ ~r/set home/i
    end
  end

  describe "location" do
    test "the tree line is set here, a slider a direction, and every sky follows it", %{conn: conn} do
      before = Controller.Settings.get("horizon")
      on_exit(fn -> Controller.Settings.put("horizon", before) end)
      {:ok, view, html} = live(conn, "/location")
      assert html =~ "Tree Line"
      assert html =~ ~s(type="range")
      assert html =~ ~s(id="tree-dome")

      render_change(view, "horizon", Map.new(~w(N NE E SE S SW W NW), &{&1, "35"}))
      assert Controller.Settings.horizon()["SW"] == 35

      render_click(view, "horizon_clear", %{})
      assert Controller.Settings.horizon()["SW"] == 0
    end

    test "over plain http the phone-location key is greyed out and says why", %{conn: conn} do
      {:ok, _view, html} = live(conn, "http://10.0.1.44/location")
      assert html =~ "only with https pages"
      assert html =~ ~r/id="use-phone-location"[^>]*disabled/
    end
  end

  describe "object" do
    test "shows a blurb and slew button", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/object/m31?mount=#{id}")
      assert html =~ "Andromeda"
      assert html =~ "2.5 million light-years"
      assert html =~ "Go To"
      # its night: the path across the sky and the altitude curve
      assert html =~ ~s(id="object-path")
      assert html =~ "Its altitude through the night"
    end

    test "unknown object is a soft 404", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/object/nope")
      assert html =~ "Nothing called"
    end
  end

  describe "setup and devices" do
    test "setup shows modes and can set home", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/setup/#{id}")
      assert html =~ "Sync offset"
      render_click(view, "home", %{})
      assert Mount.snapshot(id).homed
    end

    test "devices is a list of hardware, each row opening that device's page", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/devices")
      assert html =~ id
      assert html =~ ~s(href="/devices/mount/#{id}")
      assert html =~ "Answering"
      for section <- ["Mounts", "Cameras", "Game Controllers", "This Machine"], do: assert(html =~ section)
      # driving is on Controls, not here
      refute html =~ "Drive It"
    end

    test "a mount's own page says what it is and how to use it", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/devices/mount/#{id}")
      assert html =~ "Simulator"
      assert html =~ "Answering"
      assert html =~ ~s(href="/setup/#{id}")
      assert html =~ "STOP"

      {:ok, _view, html} = live(conn, "/devices/mount/gone")
      assert html =~ "No mount called gone right now"
    end
  end

  describe "home" do
    test "the front door is the flow: four steps, the current one first", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/alignment")
      for step <- ["Plug In", "Set Home", "Stars 0/3", "Look"], do: assert(html =~ step)
      # a simulated mount is connected but home is not set: step 2 is on
      assert html =~ "Set Home Here"
      refute html =~ "Look At"
      assert html =~ "How This Works"
    end

    test "the scopes themselves come first, live, one badge each", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/")
      assert html =~ "scope-badge"
      assert html =~ id
      assert html =~ "Home not set"
      # the badge draws the mount, with a rim so it reads on the card, and says the numbers for a screen reader
      assert html =~ ~s(role="img")
      assert html =~ ~s(class="sc-outline")
      assert html =~ "RA axis +0°00′"

      Mount.set_home(id)
      assert render(view) =~ "Home set, still"
    end

    # The badge's two numbers are where the axes stand, in degrees from home. Under "RA" and
    # "Dec" they read, once the mount was aligned, as where it points on the sky, and they are
    # not that. So each is called an axis angle, aligned or not.
    test "aligned, the badge still calls its two numbers what they are: RA axis and Dec axis", %{conn: conn, id: id} do
      alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars}

      :ok = Mount.set_home(id)
      on_exit(fn -> Lineup.clear(id) end)

      # a known alignment: three stars as a mount set down 30° round and 6° high would show them
      truth = %{axis_alt: 43.9, axis_az: 330.0, off_ra: 12.0, off_dec: -4.0}
      now = DateTime.utc_now()
      site = Pointing.site()

      for name <- ["Vega", "Altair", "Arcturus"] do
        star = Enum.find(Stars.all(), &(&1.name == name))
        {alt, az} = Astro.alt_az(star.ra_deg, star.dec_deg, site.lat, Astro.lst_deg(now, site.lon))
        {r, d} = Model.encoders(truth, Pointing.pointing(), alt, az)
        Lineup.add(%{id: id, homed: true, connected: true, tracking: :off, axes: %{ra: %{degrees: r}, dec: %{degrees: d}}}, star, now)
      end

      assert Pointing.lined_up?(Pointing.context(DateTime.utc_now(), id))

      # the axes 10° and −5° from home
      :ok = Mount.goto_relative(id, :ra, 10.0)
      :ok = Mount.goto_relative(id, :dec, -5.0)
      landed = fn -> Enum.all?(Mount.snapshot(id).axes, fn {_, axis} -> not Map.get(axis, :goto_pending, false) and not axis.running end) end
      assert Enum.find(1..300, fn _ -> landed.() or (Process.sleep(50) && false) end), "the simulated mount never landed"
      snap = Mount.snapshot(id)
      assert_in_delta snap.axes.ra.degrees, 10.0, 0.001
      assert_in_delta snap.axes.dec.degrees, -5.0, 0.001

      {:ok, view, _html} = live(conn, "/")
      badge = view |> element(~s(a.scope-badge[href="/setup/#{id}"])) |> render()

      # each number beside its name, on the card and in what a screen reader is told
      assert badge =~ ~r/<span class="sb-num">\s*RA axis \+10°00′\s*<\/span>\s*<span class="sb-num">\s*Dec axis −5°00′\s*<\/span>/
      assert badge =~ "RA axis +10°00′, Dec axis −5°00′"
      # no number under a bare "RA" or "Dec", in the text, the label or the drawing's own words
      refute badge =~ ~r/\b(RA|Dec) [+−-]?\d/u

      # where it points on the sky is another number altogether: with this alignment, Dec in the sixties
      {_ra, dec} = Pointing.scope_radec(snap, Pointing.context(DateTime.utc_now(), id))
      refute_in_delta dec, -5.0, 30.0
    end

    test "everything else lists every group with one line each", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/")
      for name <- ["Alignment", "Sky", "Controls", "Cameras", "Mount", "System", "All Cameras", "Observatory Camera", "Status", "Align by Stars", "Orb", "Events"], do: assert(html =~ name)
      assert html =~ "Center a few stars"
    end
  end

  describe "events" do
    test "commands to the mount show up with their source", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/nudge/#{id}")
      render_click(view, "nudge", %{"dir" => "right"})
      Process.sleep(100)
      {:ok, _view, html} = live(conn, "/events")
      assert html =~ "page · Nudge"
      assert html =~ "#{id} · RA by"
    end

    test "a Go To the mount did not start, and tracking that gave up, are said in plain words (#122)", %{conn: conn, id: id} do
      Telescope.Events.emit(:mount, :goto_failed, %{id: id, axis: :dec, why: :goto_not_started})
      Telescope.Events.emit(:tracker, :end, %{id: id, target: "M31", why: :lost, off_deg: 23.1})
      Process.sleep(100)
      {:ok, _view, html} = live(conn, "/events")
      assert html =~ "#{id} · Dec Go To did not start: the mount took the command and did not move"
      assert html =~ "Gave up tracking M31: 23.1° off, too far to chase. The mount is not tracking"
    end
  end

  describe "docs" do
    test "markdown pages render", %{conn: conn} do
      # the page's title is the toolbar's h1, like every page's; headings carry ids, so a hint can link to a section
      assert get(conn, "/docs/magnitude") |> html_response(200) =~ ~s(<h1 class="page-title">Magnitude, in plain words</h1>)
      assert get(conn, "/docs/glossary") |> html_response(200) =~ ~s(id="home-position")
      assert get(conn, "/docs/nope") |> response(404)
    end
  end

  # WCAG 2.1 (DESIGN.md, "Accessible by default"): the things a regex over the
  # rendered page can vouch for, on every route, against the simulator.
  describe "accessibility" do
    defp routes(id) do
      [
        "/", "/alignment", "/controls/scope/#{id}", "/controls/eyepiece/#{id}", "/#{id}", "/sky/#{id}", "/object/m31?mount=#{id}", "/controls/orb/#{id}", "/events",
        "/devices", "/devices/ports", "/devices/boxes", "/devices/mount/#{id}", "/input?mount=#{id}", "/tonight/#{id}",
        "/cameras", "/cameras/telescope", "/cameras/telescope/focus", "/cameras/telescope/settings", "/search",
        "/cameras/observatory", "/cameras/observatory/frames", "/cameras/observatory/settings", "/controls/watch/axes/#{id}",
        "/controls/dpad/#{id}", "/controls/nudge/#{id}", "/controls/position/#{id}", "/controls/align/#{id}", "/align/photo/#{id}",
        "/controls/center/#{id}", "/setup/#{id}", "/docs/keypad"
      ]
    end

    defp pages(conn, id), do: for(path <- routes(id), do: {path, get(conn, path) |> html_response(200)})

    test "every page: lang, one main, one h1, a skip link to one content anchor", %{conn: conn, id: id} do
      for {path, html} <- pages(conn, id) do
        assert html =~ ~s(<html lang="en">), path
        assert length(Regex.scan(~r/<main\b/, html)) == 1, "#{path}: one <main> per document"
        assert length(Regex.scan(~r/<h1\b/, html)) == 1, "#{path}: one <h1> per page"
        assert html =~ ~s(href="#content"), "#{path}: skip link"
        assert length(Regex.scan(~r/id="content"/, html)) == 1, "#{path}: one skip target"
        # no id appears twice (nested pages must not repeat the parent's)
        ids = Regex.scan(~r/ id="([^"]+)"/, html) |> Enum.map(fn [_, i] -> i end)
        assert ids == Enum.uniq(ids), "#{path}: duplicate ids #{inspect(ids -- Enum.uniq(ids))}"
      end
    end

    test "every page has its own title", %{conn: conn, id: id} do
      titles =
        for {path, html} <- pages(conn, id) do
          [_, title] = Regex.run(~r/<title[^>]*>([^<]*)<\/title>/, html)
          refute title == "Observatory", "#{path}: no page title set"
          assert title =~ " · Observatory", path
          title
        end

      assert titles == Enum.uniq(titles), "titles repeat: #{inspect(titles -- Enum.uniq(titles))}"
    end

    test "icon-only buttons have names; pictures have alt text or are hidden", %{conn: conn, id: id} do
      for {path, html} <- pages(conn, id) do
        for [tag, attrs, inner] <- Regex.scan(~r/<button\b([^>]*)>(.*?)<\/button>/s, html) do
          text = inner |> String.replace(~r/<[^>]+>/, "") |> String.trim()
          assert text != "" or attrs =~ "aria-label=", "#{path}: button without a name: #{String.slice(tag, 0, 80)}"
        end

        for [tag] <- Regex.scan(~r/<svg\b[^>]*>/, html) do
          assert tag =~ ~s(aria-hidden="true") or tag =~ ~s(role="img"), "#{path}: svg is neither labelled nor decorative: #{String.slice(tag, 0, 80)}"
        end

        for [tag] <- Regex.scan(~r/<img\b[^>]*>/, html), do: assert(tag =~ "alt=", "#{path}: img without alt: #{tag}")

        # a raised key that toggles says which way it is; a segmented control is a radio group
        for [tag] <- Regex.scan(~r/<button[^>]*phx-click="night"[^>]*>/, html), do: assert(tag =~ "aria-pressed=", path)
        for [tag] <- Regex.scan(~r/<div class="seg[^"]*"[^>]*>/, html), do: assert(tag =~ ~s(role="radiogroup"), path)
      end
    end

    test "the plain keypad and the orb take arrow keys and stop on Escape", %{conn: conn, id: id} do
      for path <- ["/controls/dpad/#{id}", "/controls/orb/#{id}"] do
        {:ok, view, _} = live(conn, path)
        render_keydown(view, "keydown", %{"key" => "ArrowRight"})
        assert Mount.snapshot(id).axes.ra.running, path
        render_keyup(view, "keyup", %{"key" => "ArrowRight"})
        refute Mount.snapshot(id).axes.ra.running, path

        render_keydown(view, "keydown", %{"key" => "ArrowUp"})
        assert Mount.snapshot(id).axes.dec.running, path
        render_keydown(view, "keydown", %{"key" => "Escape"})
        refute Mount.snapshot(id).axes.dec.running, path
      end
    end

    test "the keypad stops on Escape as well as space", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/#{id}")
      Mount.slew(id, :dec, 64)
      assert Mount.snapshot(id).axes.dec.running
      render_keydown(view, "keydown", %{"key" => "Escape"})
      refute Mount.snapshot(id).axes.dec.running
    end

    test "a bad position target is named, not swallowed", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/position/#{id}")
      render_change(view, "targets", %{"ra" => "twelve", "dec" => "0"})
      assert render_click(view, "go", %{"axis" => "ra"}) =~ "RA target must be a number"
    end
  end
end
