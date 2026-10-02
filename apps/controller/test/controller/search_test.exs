defmodule Controller.SearchTest do
  @moduledoc """
  Finding a page by typing a bit of its name (⌘K on a computer, the search
  key on a phone), and the cameras, together under /cameras.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Search

  defp titles(q, opts \\ []), do: q |> Search.find(opts) |> Enum.map(&{&1.title, &1.where})

  describe "finding" do
    test "a word that starts a page's name finds it first" do
      assert hd(titles("foc")) == {"Focus", "Cameras"}
      assert hd(titles("site")) == {"Site", "Alignment"}
    end

    test "words match anywhere in the name or where it lives: \"cam set\" is a camera's Settings" do
      found = titles("cam set")
      assert {"Settings", "Telescope Camera"} in found
      assert {"Settings", "Observatory Camera"} in found
      refute {"Site", "Alignment"} in found
    end

    test "every word has to match" do
      assert titles("focus banana") == []
    end

    test "letters in order still find a name, last" do
      assert {"Telescope Camera", "Cameras"} in titles("tlscp")
    end

    test "the docs are found too, as help, by their titles and by words only their text has" do
      assert {"Magnitude, in plain words", "Help"} in titles("magnitude")
      assert Enum.any?(Search.find("plate"), &(&1.kind == :doc))
    end

    test "nothing typed: this page's help first, then every page in sidebar order" do
      [help, first | _] = Search.find("", here: "/cameras/telescope/settings")
      assert help.title == "Help: Telescope Camera"
      assert help.path == "/docs/scope-camera"
      assert first.title == "Start"
      assert hd(Search.find("")).title == "Start"
    end
  end

  describe "search on every page" do
    test "the popover is on a page, with a key to open it; typing lists matches; Enter goes", %{conn: conn} do
      {:ok, view, html} = live(conn, ~p"/cameras")
      assert html =~ ~s(id="spotlight")
      assert html =~ ~s(popovertarget="spotlight")
      assert html =~ ~s(aria-label="Search")

      html = view |> element("#spotlight form") |> render_change(%{"q" => "focus"})
      assert html =~ ~s(aria-selected="true")
      assert html =~ "Focus"
      view |> element("#spotlight-input") |> render_keydown(%{"key" => "ArrowDown"})
      view |> element("#spotlight form") |> render_change(%{"q" => "foc"})
      assert {:error, {:live_redirect, %{to: "/cameras/telescope/focus"}}} = view |> element("#spotlight form") |> render_submit()
    end

    test "the search page, for where the popover can't open", %{conn: conn} do
      {:ok, view, html} = live(conn, ~p"/search")
      assert html =~ "All Cameras"
      assert view |> element(".search-page-form") |> render_change(%{"q" => "queue"}) =~ "Queues"
    end
  end

  describe "cameras" do
    test "All Cameras shows each camera with its name and how it is", %{conn: conn} do
      {:ok, _view, html} = live(conn, ~p"/cameras")
      assert html =~ "Telescope Camera"
      assert html =~ "Observatory Camera"
      assert html =~ ~s(href="/cameras/telescope")
      assert html =~ ~s(href="/cameras/observatory")
    end

    test "the sidebar has one Cameras group: All Cameras, Telescope Camera, Focus, Observatory Camera" do
      {"Cameras", _, pages} = List.keyfind(Controller.Nav.groups(), "Cameras", 0)
      assert Enum.map(pages, & &1.title) == ["All Cameras", "Telescope Camera", "Focus", "Observatory Camera"]
      # a camera's settings mark the camera in the sidebar
      assert Controller.Nav.current("/cameras/observatory/settings") == "/cameras/observatory"
    end

    test "one list of pages: every page in the sidebar is on a phone's Home and in Search, with its icon", %{conn: conn} do
      {:ok, _view, home} = live(conn, ~p"/")
      found = Search.find("") |> Enum.map(& &1.path) |> MapSet.new()

      for p <- Controller.Nav.pages() do
        assert home =~ ~s(href="#{p.path}"), "#{p.title} on Home"
        assert p.path in found, "#{p.title} in Search"
        assert p.icon != "dot", "#{p.title} has an icon"
      end

      # no page is listed twice, and no page lives at two addresses
      paths = Enum.map(Controller.Nav.pages() ++ Controller.Nav.under(), & &1.path)
      assert paths == Enum.uniq(paths)
    end

    test "a page with a mount in its address marks its entry in the sidebar" do
      assert Controller.Nav.current("/keypad/eq6r") == "/keypad"
      assert Controller.Nav.current("/sky/eq6r") == "/sky"
      assert Controller.Nav.current("/object/m31") == "/sky"
      assert Controller.Nav.current("/controls/dpad/eq6r") == "/controls/dpad"
      assert Controller.Nav.current("/") == nil
    end

    test "the old addresses still land, the rest of the path and the query carried over", %{conn: conn} do
      assert redirected_to(get(conn, "/scope-camera"), 301) == "/cameras/telescope"
      assert redirected_to(get(conn, "/scope-camera/focus"), 301) == "/cameras/telescope/focus"
      assert redirected_to(get(conn, "/scope-camera/frames/12?x=1"), 301) == "/cameras/telescope/frames/12?x=1"
      assert redirected_to(get(conn, "/controls/watch"), 301) == "/cameras/observatory"
      assert redirected_to(get(conn, "/controls/watch/camera"), 301) == "/cameras/observatory/settings"
      # the axes page didn't move
      refute get(conn, "/controls/watch/axes").status == 301
    end

    test "a camera's line says whether it's there and live" do
      assert Controller.CamerasLive.telescope_line(%{camera: nil}, nil, nil) =~ "Plug it into"
      assert Controller.CamerasLive.telescope_line(%{camera: %{}, live: true}, %{seq: 4}, nil) == "Live · frame 4"
    end
  end
end
