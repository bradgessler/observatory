defmodule Controller.ProvisionTest do
  @moduledoc "The stamping page: safe by default, and never quiet while it works."
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  test "it lists no internal drives, and will not write until a card is chosen", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/provision")
    assert html =~ "The Card"
    assert html =~ "Choose a card first"
    # the machine's own disk must never be offered
    refute html =~ "/dev/disk0"
    refute html =~ "/dev/disk1"
  end

  test "it says what will be written before anything happens", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision")
    html = render_click(view, "template", %{"id" => "mount_only"})
    assert html =~ "Mount Only"
    assert html =~ "Zero 2 W"

    html = render_click(view, "flavour", %{"id" => "dev"})
    assert html =~ "shell on this box", "a development box should say the door is open"
  end

  test "with no Wi-Fi it promises its own network; with Wi-Fi it promises to join", %{conn: conn} do
    {:ok, view, html} = live(conn, "/provision")
    assert html =~ "brings up a network of"

    html = render_change(view, "details", %{"hostname" => "barn", "wifi_ssid" => "Barn", "wifi_psk" => "hunter2"})
    assert html =~ "Joins Barn"
    assert html =~ "barn.local"
    # the password is in a password field, not a readable one
    assert html =~ ~r/<input[^>]*name="wifi_psk"[^>]*type="password"|<input[^>]*type="password"[^>]*name="wifi_psk"/
  end

  test "the steps of a job are named before it starts", %{conn: conn} do
    {:ok, _view, _} = live(conn, "/provision")
    names = Provision.Job.steps() |> Enum.map(&elem(&1, 1))
    assert "Checking the card" in names
    assert "Writing to the card" in names
  end
end
