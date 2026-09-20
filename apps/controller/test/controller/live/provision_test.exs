defmodule Controller.ProvisionTest do
  @moduledoc """
  The stamping flow: one decision per screen, safe by default, and never quiet
  while it works.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  test "the first screen asks for a card and nothing else", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/provision")

    assert html =~ "The Card"
    # the later decisions must not be on this screen
    refute html =~ "Pi Zero"
    refute html =~ "Wi-Fi network"
    refute html =~ "Write It"

    # the machine's own disk must never be offered
    refute html =~ "/dev/disk0"
    refute html =~ "/dev/disk1"
  end

  test "each step is its own URL, and the strip says where you are", %{conn: conn} do
    for {step, title} <- [
          {"card", "The Card"},
          {"role", "What It Does"},
          {"machine", "The Machine"},
          {"network", "Reaching It"},
          {"write", "Write It"}
        ] do
      {:ok, _view, html} = live(conn, "/provision/#{step}")
      assert html =~ title, "#{step} should show #{title}"
      assert html =~ ~s(aria-current="step"), "#{step} should mark its place in the strip"
    end
  end

  test "picking a job carries you forward and brings the machine with it", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/role")

    html = render_click(view, "template", %{"id" => "mount_only"})

    # tapping the choice is the way forward: we land on the machine screen
    assert html =~ "The Machine"
    # and a mount-only box has already suggested the small machine
    assert html =~ "Pi Zero 2 W"
    assert html =~ "Suits Mount Only"
  end

  test "an unchosen machine can still be overridden, and that sticks", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/role")
    render_click(view, "template", %{"id" => "mount_only"})
    render_click(view, "target", %{"id" => "rpi5"})

    html = render_click(view, "go", %{"step" => "write"})
    assert html =~ "Mount Only on a Pi 5"
  end

  test "the door screen says what an open box costs", %{conn: conn} do
    {:ok, view, html} = live(conn, "/provision/network")
    # production is the default, and says nothing alarming
    refute html =~ "open a shell"

    html = render_click(view, "flavour", %{"id" => "dev"})
    assert html =~ "open a shell on it", "a development box should say the door is open"
  end

  test "with no Wi-Fi it promises its own network; with Wi-Fi it promises to join", %{conn: conn} do
    {:ok, view, html} = live(conn, "/provision/network")
    assert html =~ "observatory-setup"

    html = render_change(view, "details", %{"hostname" => "barn", "wifi_ssid" => "Barn", "wifi_psk" => "hunter2"})
    assert html =~ "barn.local"
    assert html =~ "barn-setup"

    # the password is in a password field, not a readable one
    assert html =~ ~r/<input[^>]*name="wifi_psk"[^>]*type="password"|<input[^>]*type="password"[^>]*name="wifi_psk"/

    html = render_click(view, "go", %{"step" => "write"})
    assert html =~ "Joins Barn"
  end

  test "it will not write without a card, and says so plainly", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/provision/write")
    assert html =~ "No card chosen"
    assert html =~ ~s(disabled)
  end

  test "the steps of a job are named before it starts", %{conn: conn} do
    {:ok, _view, _} = live(conn, "/provision")
    names = Provision.Job.steps() |> Enum.map(&elem(&1, 1))
    assert "Checking the card" in names
    assert "Writing to the card" in names
  end
end
