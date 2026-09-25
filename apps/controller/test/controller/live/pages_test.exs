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
    test "renders the map, tonight and horizon tabs", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/sky/#{id}")
      assert html =~ "Tonight"
      assert view |> element("button", "Tonight") |> render_click() =~ "Above your tree line"
      assert view |> element("button", "Horizon") |> render_click() =~ "aperture"
    end

    test "slewing before home explains itself", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/sky/#{id}")
      render_click(view, "pick", %{"id" => "m13"})
      assert render_click(view, "goto", %{}) =~ ~r/zero the axes/i
    end
  end

  describe "object" do
    test "shows a blurb and slew button", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/object/m31?mount=#{id}")
      assert html =~ "Andromeda"
      assert html =~ "2.5 million light-years"
      assert html =~ "Slew"
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

    test "devices lists the simulated mount", %{conn: conn, id: id} do
      {:ok, _view, html} = live(conn, "/devices")
      assert html =~ id
      assert html =~ "Drive It"
    end
  end

  describe "home" do
    test "the front door is the flow: four steps, the current one first", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/start")
      for step <- ["Plug in", "Zero", "Stars 0/3", "Look"], do: assert(html =~ step)
      # a simulated mount is connected but not zeroed: step 2 is on
      assert html =~ "Zero the Axes Here"
      refute html =~ "Look At"
      assert html =~ "Home ›"
    end

    test "the scopes themselves come first, live, one badge each", %{conn: conn, id: id} do
      {:ok, view, html} = live(conn, "/")
      assert html =~ "scope-badge"
      assert html =~ id
      assert html =~ "Not zeroed"
      # the badge draws the mount, and says the numbers for a screen reader
      assert html =~ ~s(role="img")
      assert html =~ "RA +0°00′"

      Mount.set_home(id)
      assert render(view) =~ "Zeroed, still"
    end

    test "everything else lists every group with one line each", %{conn: conn} do
      {:ok, _view, html} = live(conn, "/")
      for name <- ["Star Lock", "Controls", "Watch", "Plumbing", "Start", "Star Align", "Orb", "Bench"], do: assert(html =~ name)
      assert html =~ "Name a few stars"
    end
  end

  describe "events" do
    test "commands to the mount show up with their source", %{conn: conn, id: id} do
      {:ok, view, _} = live(conn, "/controls/nudge/#{id}")
      render_click(view, "nudge", %{"dir" => "right"})
      Process.sleep(100)
      {:ok, _view, html} = live(conn, "/events")
      assert html =~ "page · Nudge"
      assert html =~ "#{id} · ra by"
    end
  end

  describe "docs" do
    test "markdown pages render", %{conn: conn} do
      assert get(conn, "/docs/magnitude") |> html_response(200) =~ "<h1>"
      assert get(conn, "/docs/nope") |> response(404)
    end
  end

  # WCAG 2.1 (DESIGN.md, "Accessible by default"): the things a regex over the
  # rendered page can vouch for, on every route, against the simulator.
  describe "accessibility" do
    defp routes(id) do
      [
        "/", "/start", "/controls/scope/#{id}", "/controls/eyepiece/#{id}", "/#{id}", "/sky/#{id}", "/object/m31?mount=#{id}", "/controls/orb/#{id}", "/events",
        "/devices", "/devices/ports", "/input?mount=#{id}", "/bench?mount=#{id}", "/bench/sky?mount=#{id}",
        "/controls/watch", "/controls/watch/frames", "/controls/watch/camera", "/controls/watch/axes/#{id}",
        "/controls/dpad/#{id}", "/controls/nudge/#{id}", "/controls/position/#{id}", "/controls/align/#{id}",
        "/controls/tilt/#{id}", "/setup/#{id}", "/docs/keypad"
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
      for path <- ["/controls/dpad/#{id}", "/controls/orb/#{id}", "/controls/tilt/#{id}"] do
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
