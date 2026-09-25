defmodule Stamp.LiveTest do
  @moduledoc """
  The stamping flow: one decision per screen, safe by default, and never quiet
  while it works.
  """
  use Stamp.ConnCase, async: false
  import Phoenix.LiveViewTest

  # saved scripts go to a folder of the test's own, never ~/.observatory
  setup do
    dir = Path.join(System.tmp_dir!(), "stamps-#{System.unique_integer([:positive])}")
    Application.put_env(:provision, :scripts_dir, dir)

    on_exit(fn ->
      Application.delete_env(:provision, :scripts_dir)
      File.rm_rf(dir)
    end)

    %{dir: dir}
  end

  test "the first screen asks for a card and nothing else", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/provision")

    assert html =~ "SD Card"
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
          {"card", "SD Card"},
          {"role", "Role"},
          {"machine", "Board"},
          {"network", "Access Point"},
          {"write", "Build"}
        ] do
      {:ok, _view, html} = live(conn, "/provision/#{step}")
      assert html =~ title, "#{step} should show #{title}"
      assert html =~ ~s(aria-current="step"), "#{step} should mark its place in the strip"
    end
  end

  test "picking a card carries you forward", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/card")

    # <.picks> sends the choice as phx-value-id, so the handler must read "id".
    # It once read "disk": the click crashed the view, which silently remounted
    # on the same screen and looked exactly like a dead button.
    html = render_click(view, "pick", %{"id" => "/dev/disk99"})

    assert html =~ "Role"
  end

  test "picking a job carries you forward and brings the machine with it", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/role")

    html = render_click(view, "template", %{"id" => "mount_only"})

    # tapping the choice is the way forward: we land on the machine screen
    assert html =~ "Board"
    # and a mount-only box has already suggested the small machine
    assert html =~ "Pi Zero 2 W"
    assert html =~ "Suits Mount only"
  end

  test "an unchosen machine can still be overridden, and that sticks", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/role")
    render_click(view, "template", %{"id" => "mount_only"})
    render_click(view, "target", %{"id" => "rpi5"})

    html = render_click(view, "go", %{"step" => "write"})
    assert html =~ "Mount only" and html =~ "Raspberry Pi 5"
  end

  test "the SSH setting says what it costs", %{conn: conn} do
    # SSH is what is on the box, so it is chosen with the build, not the network
    {:ok, view, html} = live(conn, "/provision/write")
    # production is the default, and says nothing alarming
    refute html =~ "gets a shell"

    html = render_click(view, "flavour", %{"id" => "dev"})
    assert html =~ "gets a shell on the box", "SSH on should say who can get in"
  end

  test "the network screen starts filled in with what the box will really do", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/provision/network")

    # its own network is named after it and already has a password; nothing
    # blank that means something, and no "-setup" network the box never makes
    assert html =~ "observatory.local"
    assert html =~ ~r/name="ap_psk"[^>]*value="[a-z2-9]{4}-[a-z2-9]{4}"/
    refute html =~ "setup"
    refute html =~ "Leave blank"
  end

  test "home Wi-Fi is optional, and joining it is said plainly", %{conn: conn} do
    {:ok, view, html} = live(conn, "/provision/network")
    # with no client network it says what the radio does: access point from boot
    assert html =~ "One: client or access point"
    assert html =~ ~r/At boot.*Access point/s

    render_change(view, "details", %{"hostname" => "barn"})
    html = render_change(view, "details", %{"wifi_ssid" => "Barn", "wifi_psk" => "hunter2x"})
    assert html =~ "Joins Barn by DHCP"
    assert html =~ "barn.local"

    # the password is in a password field, not a readable one
    assert html =~ ~r/<input[^>]*name="wifi_psk"[^>]*type="password"|<input[^>]*type="password"[^>]*name="wifi_psk"/

    html = render_click(view, "go", %{"step" => "write"})
    assert html =~ "Wi-Fi client on Barn"
  end

  test "a saved home password is never sent back to the page", %{conn: conn} do
    Provision.Scripts.save(template: :observatory, target: :rpi3, flavour: :dev, hostname: "roof", ap_psk: "field-pass", wifi: %{ssid: "Home", psk: "secret-home-pw"})

    # anyone on the network can open this page; the password stays on the server
    {:ok, view, html} = live(conn, "/provision/network")
    assert html =~ "Home"
    refute html =~ "secret-home-pw"
    assert html =~ "Saved. Type to replace"

    # and an untouched field keeps it: saving again still joins the network
    render_click(view, "go", %{"step" => "write"})
    render_click(view, "save_script", %{})
    assert {:ok, opts} = Provision.Scripts.load(Path.join(Provision.Scripts.dir(), "roof-rpi3.sh"))
    assert opts[:wifi][:psk] == "secret-home-pw"
  end

  test "the access point SSID follows the hostname until someone types one", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/network")
    ssid = fn html -> Regex.run(~r/name="ap_ssid"[^>]*value="([^"]*)"/, html) |> List.last() end

    assert ssid.(render_change(view, "details", %{"hostname" => "barn"})) == "barn"
    assert ssid.(render_change(view, "details", %{"ap_ssid" => "Star Party"})) == "Star Party"
    # once typed, it stays put when the hostname changes
    assert ssid.(render_change(view, "details", %{"hostname" => "roof"})) == "Star Party"

    render_click(view, "go", %{"step" => "write"})
    assert render(view) =~ "Access point Star Party"
  end

  test "a password Wi-Fi would refuse is caught before a ten-minute build", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/network")
    html = render_change(view, "details", %{"ap_psk" => "short"})
    assert html =~ "8 to 63 characters"
  end

  test "Stamp saves the configuration and goes straight to the running terminal", %{conn: conn, dir: dir} do
    {:ok, view, html} = live(conn, "/provision/write")
    assert html =~ ~r/phx-click="save_script"[^>]*>\s*Stamp\s*</

    render_click(view, "template", %{"id" => "observatory"})
    render_click(view, "target", %{"id" => "rpi3"})
    render_change(view, "details", %{"hostname" => "barn", "wifi_ssid" => "", "wifi_psk" => ""})
    render_click(view, "go", %{"step" => "write"})
    html = render_click(view, "save_script", %{})

    # the script is on disk, and readable by its owner alone: it can hold a
    # Wi-Fi password
    path = Path.join(dir, "barn-rpi3.sh")
    assert File.exists?(path)
    assert File.stat!(path).mode |> Bitwise.band(0o077) == 0

    # and we are on the Stamp screen: the terminal, titled with the
    # configuration it is running, and nothing else
    assert html =~ ~s(phx-hook="Terminal")
    assert html =~ "barn-rpi3.sh"
    refute html =~ "Saved Scripts", "the list belongs on the first screen, not beside a running stamp"
  end

  test "a saved stamp is offered on the first screen", %{conn: conn} do
    Provision.Scripts.save(template: :observatory, target: :rpi4, flavour: :prod, hostname: "roof", wifi: %{ssid: "", psk: ""})

    {:ok, _view, html} = live(conn, "/provision/card")
    assert html =~ "Saved Scripts"
    assert html =~ "roof-rpi4.sh"
  end

  # A phone on the same Wi-Fi: another address, not this machine's.
  defp from_phone(conn),
    do: Plug.Conn.put_private(conn, :live_view_connect_info, %{peer_data: %{address: {10, 9, 9, 9}, port: 5_555, ssl_cert: nil}})

  test "a phone watches the terminal, and types only once the Mac allows it", %{conn: conn} do
    on_exit(fn -> Provision.Terminal.allow_lan(false) end)
    Provision.Terminal.allow_lan(false)

    {:ok, phone, html} = live(from_phone(conn), "/provision/run")
    assert html =~ "Read-only on this device"
    refute html =~ "Phone input off", "only the Mac gets the switch"

    # the phone cannot let itself in
    render_click(phone, "allow_lan", %{"on" => "true"})
    refute Provision.Terminal.allow_lan?()

    # someone at the Mac turns it on, and the phone's page follows
    {:ok, mac, _} = live(conn, "/provision/run")
    render_click(mac, "allow_lan", %{"on" => "true"})
    assert Provision.Terminal.allow_lan?()
    assert render(phone) =~ "Ctrl-C", "the phone gets the keys it has no key for"
  end

  test "the page runs only scripts from its own list, never a path it is handed", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/card")

    render_click(view, "run_script", %{"id" => "/tmp/anything.sh"})
    refute render(view) =~ "anything.sh"
  end

  test "a tool installed while the page is open stops it complaining", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/card")

    # "can this machine write at all" was once answered only at mount, so the
    # page went on naming a missing tool long after it had been installed
    send(view.pid, :rescan)
    html = render(view)

    case Provision.ready?() do
      :ok -> refute html =~ "is not installed"
      {:error, why} -> assert html =~ why
    end
  end

  test "a job that failed can be answered by changing something", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/write")

    # a job that ended fills the screen; until it is put away there is no route
    # back to the choices, which is how a failure used to become a dead end
    send(view.pid, {:provision, failed_job()})
    html = render(view)
    assert html =~ "Try Again"
    assert html =~ "Change Something"

    html = render_click(view, "change", %{})

    # the five screens are back, on the summary, ready to be changed
    assert html =~ ~r/<button[^>]*phx-click="save_script"[^>]*>\s*Stamp\s*</
    refute html =~ "Change Something"
  end

  test "a finished job offers another card, and the flow comes back", %{conn: conn} do
    {:ok, view, _} = live(conn, "/provision/write")

    send(view.pid, {:provision, done_job()})
    assert render(view) =~ "Stamp Another"

    html = render_click(view, "another", %{})
    assert html =~ "SD Card"
  end

  defp failed_job, do: %{Provision.status() | error: "fwup said no", done: false, running: false}
  defp done_job, do: %{Provision.status() | error: nil, done: true, running: false}

  test "the steps of a job are named before it starts", %{conn: conn} do
    {:ok, _view, _} = live(conn, "/provision")
    names = Provision.Job.steps() |> Enum.map(&elem(&1, 1))
    assert "Checking the card" in names
    assert "Writing to the card" in names
  end
end
