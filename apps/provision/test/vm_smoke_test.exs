defmodule Provision.VMSmokeTest do
  @moduledoc """
  The image, booted for real and asked questions.

  Not part of the normal suite: it needs qemu and a built x86_64 firmware, and
  it takes about a minute. Run it with

      mix test --only vm

  This is the loop that replaces a card swap. If it passes, the image boots,
  the release starts, the supervision tree comes up and the apps that are
  supposed to be running are running.
  """
  use ExUnit.Case, async: false

  @moduletag :vm
  @moduletag timeout: 600_000

  setup_all do
    # a new image boots twice (the first boot formats /data); on a busy Mac that
    # can pass three minutes
    case Provision.VM.boot(timeout: 360_000) do
      {:ok, vm} ->
        on_exit(fn -> Provision.VM.stop(vm) end)
        # Watch the radio's first minutes before any test touches the box: a
        # test asking the captive portal during the access point window is a
        # phone, and would (rightly) keep the access point.
        %{box: vm, radio: radio_after_boot(vm, 150_000)}

      {:error, why} ->
        # a missing image or qemu is a skip, not a failure: say which
        IO.puts("\n  vm smoke test skipped: #{why}\n")
        :ok
    end
  end

  test "the image boots and the release is running", %{box: vm} do
    console = Provision.VM.console(vm)
    assert console =~ "NERVES" or console =~ "Nerves"
    assert {:ok, otp} = Provision.VM.eval(vm, ":erlang.system_info(:otp_release) |> IO.puts()")
    # IEx echoes the expression's value after what it printed; the first line is the answer
    assert otp |> String.split("\n") |> hd() |> String.trim() |> String.to_integer() >= 26
  end

  test "the apps this box is for are started", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "Application.started_applications() |> Enum.map(&elem(&1, 0)) |> Enum.sort() |> inspect() |> IO.puts()")
    assert out =~ ":mount", "the mount driver should be running on the box"
    assert out =~ ":telescope", "the cluster plumbing should be running on the box"
    assert out =~ ":controller", "the page you drive it from should be running on the box"
  end

  # What a phone in a field does: join the box's network, open its address.
  # The VM stands in for the network; the request is the same one Safari sends.
  test "the page is served on port 80, dark from the first frame", %{box: vm} do
    {:ok, _} = Application.ensure_all_started(:inets)
    url = ~c"http://127.0.0.1:#{vm.web_port}/"

    assert {:ok, {{_, 200, _}, _headers, body}} = :httpc.request(:get, {url, []}, [timeout: 15_000], [])
    body = to_string(body)
    assert body =~ "Observatory"
    assert body =~ ~s(name="color-scheme" content="dark"), "a phone set to light mode must not light up white"
  end

  # The promise: every power-on is the access point first. Then, nobody having
  # joined, the client network; and that never joining (there is no radio in a
  # VM), the access point again. Built for this test with a 20 s window.
  # As built for a Pi: straight to the client network at power-on; not joined
  # (there is no radio in a VM), the access point after 45 s.
  test "power-on joins the client network; not joined, the access point after 45 s", %{radio: radio} do
    assert [{:client, t1}, {:own, t2}] = radio, "the radio went #{inspect(radio)}"
    assert t2 - t1 >= 44_000, "the client had #{t2 - t1} ms to join"
  end

  # Built for this test with a 30 s retry: with nobody on the fallback access
  # point, the client network is tried again, and (no radio) given up on again.
  test "from the fallback access point, with no phone on it, the client network is tried again", %{box: vm} do
    ok = eventually(vm, "Firmware.Wireless.history() |> Enum.map(&elem(&1, 0)) |> inspect() |> IO.puts()", "[:client, :own, :client", 120_000)
    {:ok, seen} = Provision.VM.eval(vm, "Firmware.Wireless.history() |> inspect() |> IO.puts()")
    assert ok, "the radio went #{seen}"
  end

  # A drop once joined is rejoined, never a reason to change networks: a sag as
  # the motors start must not strand the box on its own access point.
  test "once joined, a drop is rejoined; never joined, it counts down to the access point", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "IO.inspect({Firmware.Wireless.on_drop(true), Firmware.Wireless.on_drop(false)})")
    assert out =~ "{:rejoin, :countdown}"
  end

  test "the black box keeps a boot record, a flight log and the events on /data", %{box: vm} do
    {:ok, out} =
      Provision.VM.eval(vm, ~S"""
      IO.inspect({Firmware.Blackbox.boots(1), length(Firmware.Blackbox.current(50)), File.exists?("/data/observatory/events.log"), Process.whereis(Firmware.Blackbox) |> is_pid()})
      """)

    assert out =~ "boot; previous:"
    assert out =~ "true, true}"
    {:ok, flight} = Provision.VM.eval(vm, "Firmware.Blackbox.current(5) |> Enum.join(\"\\n\") |> IO.puts()")
    assert flight =~ "wlan0="
  end

  defp radio_after_boot(vm, within) do
    deadline = System.monotonic_time(:millisecond) + within

    Stream.repeatedly(fn ->
      case Provision.VM.eval(vm, "Firmware.Wireless.history() |> inspect() |> IO.puts()") do
        # printed as a keyword list, [window: 31301, client: 52018]
        {:ok, out} -> for [_, phase, ms] <- Regex.scan(~r/\b(window|kept|client|own): (\d+)/, out), do: {String.to_atom(phase), String.to_integer(ms)}
        _ -> []
      end
    end)
    |> Enum.reduce_while(nil, fn history, _ ->
      cond do
        match?([_ | _], history) and elem(List.last(history), 0) in [:own, :kept] -> {:halt, history}
        System.monotonic_time(:millisecond) > deadline -> {:halt, history}
        true -> Process.sleep(3_000) && {:cont, history}
      end
    end)
  end

  test "after the window a phone keeps the access point, and no client network means the access point", %{box: vm} do
    {:ok, out} =
      Provision.VM.eval(vm, ~S"""
      w = &Firmware.Wireless.after_window/3
      IO.inspect([w.(["aa:bb"], false, [%{ssid: "x"}]), w.([], true, [%{ssid: "x"}]), w.([], false, []), w.([], false, [%{ssid: "x"}])])
      """)

    assert out =~ "[:kept, :kept, :own, :client]"
  end

  # With a client network stamped in, wlan0 boots as its client: the access
  # point never beacons at power-on for a phone to grab. Nothing VintageNet
  # saves may replace that.
  test "wlan0 boots as a client of the stamped network, and nothing is persisted over it", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "IO.inspect({Application.get_env(:vintage_net, :persistence), Application.get_env(:vintage_net, :config) |> Enum.find_value(fn {\"wlan0\", c} -> hd(c.vintage_net_wifi.networks) |> Map.get(:mode, :client); _ -> nil end)})")
    assert out =~ "{VintageNet.Persistence.Null, :client}"
  end

  defp eventually(vm, code, expected, within),
    do: poll(vm, code, expected, System.monotonic_time(:millisecond) + within)

  defp poll(vm, code, expected, deadline) do
    case Provision.VM.eval(vm, code) do
      {:ok, out} -> if out =~ expected, do: true, else: again(vm, code, expected, deadline)
      _ -> again(vm, code, expected, deadline)
    end
  end

  defp again(vm, code, expected, deadline) do
    if System.monotonic_time(:millisecond) > deadline do
      false
    else
      Process.sleep(3_000)
      poll(vm, code, expected, deadline)
    end
  end

  # There is no radio in a VM, but the same library that drives the Pi's radio
  # writes the file it would hand to it, and that file can be read here.
  test "its own network is a WPA2 access point a phone will join", %{box: vm} do
    code =
      ~S[cfg = Application.fetch_env!(:firmware, :own_network); raw = VintageNetWiFi.to_raw_config("wlan0", cfg, tmpdir: "/tmp", regulatory_domain: "US"); raw.files |> Enum.find_value(fn {p, c} -> if String.contains?(p, "wpa_supplicant.conf"), do: c end) |> IO.puts()]

    {:ok, conf} = Provision.VM.eval(vm, code)
    assert conf =~ "mode=2", "it should be an access point, not a client"

    if conf =~ "key_mgmt=WPA-PSK" do
      # AES only: a network offering TKIP is one phones refuse to join. (WPA2
      # alone would need proto=RSN, which vintage_net_wifi does not write.)
      assert conf =~ "pairwise=CCMP"
      refute conf =~ "TKIP"
    else
      assert conf =~ "key_mgmt=NONE"
    end
  end

  # A house with several access points on one SSID: the box must take any of
  # them and move to a stronger one, never hold on to the one it met first.
  test "a Wi-Fi client matches by SSID alone, and roams to a stronger access point", %{box: vm} do
    code =
      ~S[cfg = Firmware.Wireless.client_config(Application.get_env(:firmware, :client_networks)); raw = VintageNetWiFi.to_raw_config("wlan0", cfg, tmpdir: "/tmp", regulatory_domain: "US"); raw.files |> Enum.find_value(fn {p, c} -> if String.contains?(p, "wpa_supplicant.conf"), do: c end) |> IO.puts()]

    {:ok, conf} = Provision.VM.eval(vm, code)
    assert conf =~ "ssid=", "built with a client network for this test"
    refute conf =~ "bssid=", "a client pinned to one access point cannot roam"
    assert conf =~ ~s(bgscan="simple:30:-70:3600")
    # hidden SSIDs found, joins not waiting on a beacon
    assert conf =~ "scan_ssid=1"

    # two blocks: what has always joined (WPA2, and WPA2/WPA3-transition) first,
    # then WPA3 and PMF-required WPA2 for a network that refuses it
    [first, second] = Regex.scan(~r/network=\{(.*?)\}/s, conf) |> Enum.map(&List.last/1)
    assert first =~ "key_mgmt=WPA-PSK\n" and first =~ "priority=1"
    refute first =~ "ieee80211w"
    assert second =~ "key_mgmt=SAE WPA-PSK-SHA256" and second =~ "ieee80211w=2" and second =~ "priority=0"
    assert conf =~ "sae_pwe=2"
  end

  # The VM has no wpa_supplicant, so the Pi's own is asked: the rpi4 system's
  # root filesystem (the same wpa_supplicant 2.12 build, WPA3 on, as every Pi
  # system here; arm64, so it runs natively under Docker on a Mac) imported
  # as a local image. The wired driver lets it start without a radio, which
  # makes it read every network block. A file it cannot parse is a box that
  # joins nothing and, for the access point, a box with no way in.
  @tag :docker
  test "the Pi's own wpa_supplicant parses the client and access point configs", %{box: vm} do
    case pi_wpa_supplicant() do
      {:skip, why} ->
        IO.puts("\n  wpa_supplicant parse check skipped: #{why}")

      {:ok, image} ->
        client =
          ~S|Firmware.Wireless.client_config([%{ssid: "Things", key_mgmt: :wpa_psk, psk: "hunter2hunter2"}, %{ssid: "Cafe", key_mgmt: :none}, %{ssid: "It's \"quoted\"", key_mgmt: :wpa_psk, psk: "correct horse battery"}])|

        for {what, cfg} <- [client: client, access_point: "Application.fetch_env!(:firmware, :own_network)"] do
          {:ok, conf} = Provision.VM.eval(vm, ~s[cfg = #{cfg}; raw = VintageNetWiFi.to_raw_config("wlan0", cfg, Application.get_all_env(:vintage_net) |> Keyword.merge(tmpdir: "/tmp", regulatory_domain: "US")); raw.files |> Enum.find_value(fn {p, c} -> if String.contains?(p, "wpa_supplicant.conf"), do: c end) |> IO.write()])
          # the file, from its first line; the remote shell's own ":ok" can land
          # on either side of what was written
          [conf] = Regex.run(~r/ctrl_interface=.*\}/s, conf)
          conf = String.replace(conf, ~r/^ctrl_interface=.*$/m, "ctrl_interface=/tmp/wpa") <> "\n"
          out = parse_with(image, conf)

          refute out =~ "Failed to read or parse", "#{what} config does not parse:\n#{conf}\n#{out}"
          assert out =~ "Added interface", "#{what} config: wpa_supplicant did not start:\n#{out}"
        end

        # and the check itself can fail: a broken file is refused
        assert parse_with(image, "network={\nssid=\"x\"\nkey_mgmt=BOGUS\n}\n") =~ "Failed to read or parse"
    end
  end

  defp pi_wpa_supplicant do
    image = "nerves-rpi4-rootfs:local"
    tar = Path.wildcard(Path.join(System.user_home!(), ".nerves/artifacts/nerves_system_rpi4-portable-*/images/rootfs.tar")) |> List.last()

    cond do
      is_nil(System.find_executable("docker")) -> {:skip, "no docker"}
      match?({_, 0}, System.cmd("docker", ["image", "inspect", image], stderr_to_stdout: true)) -> {:ok, image}
      is_nil(tar) -> {:skip, "no rpi4 system artifact to take wpa_supplicant from"}
      true ->
        case System.cmd("docker", ["import", tar, image], stderr_to_stdout: true) do
          {_, 0} -> {:ok, image}
          {out, _} -> {:skip, "docker import failed: #{out}"}
        end
    end
  end

  # Through the environment, not a mounted file: a Mac's Docker VM may not
  # share the temp directory, and a missing mount reads as an empty, valid file.
  defp parse_with(image, conf) do
    script = ~S[printf "%s" "$CONF" > /tmp/c.conf; /usr/sbin/wpa_supplicant -c /tmp/c.conf -i eth0 -D wired -dd & sleep 3; kill $! 2>/dev/null; true]
    {out, _} = System.cmd("docker", ["run", "--rm", "--platform", "linux/arm64", "-e", "CONF=" <> conf, image, "/bin/sh", "-c", script], stderr_to_stdout: true)
    out
  end

  # No radio in a VM, so no wpa_supplicant to ask: the call must say so and
  # carry on, not take the Wi-Fi process down with it.
  test "turning Wi-Fi power save off without a radio is an answer, not a crash", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "Firmware.Wireless.power_save_off() |> inspect() |> IO.puts()")
    assert out =~ ":ok" or out =~ ":error"
    {:ok, alive} = Provision.VM.eval(vm, "Process.whereis(Firmware.Wireless) |> is_pid() |> IO.puts()")
    assert alive =~ ~r/^true/
  end

  # -- a box carries the observatory, not the laptop's kit ---------------------------------

  test "the box has its own Network page, and none of the laptop's pages or apps", %{box: vm} do
    home = body(vm, "/")
    assert home =~ "Network"
    refute home =~ "Stamp a Box", "Stamp a Box is the laptop's"
    # three screens, one job each: now, the networks, joining one
    network = body(vm, "/network")
    assert network =~ "Wi-Fi Networks"
    assert network =~ "Addresses"
    assert body(vm, "/network/wifi") =~ "Saved"
    join = body(vm, "/network/join?ssid=Garden")
    assert join =~ "Password"
    assert join =~ ~s(value="Garden")

    # not hidden: absent. The apps are not in the image at all.
    {:ok, apps} = Provision.VM.eval(vm, "Application.loaded_applications() |> Enum.map(&elem(&1, 0)) |> inspect(limit: :infinity) |> IO.puts()")
    refute apps =~ ":stamp"
    refute apps =~ ":provision"
  end

  # -- the captive portal: joining the access point opens the Observatory ------------------

  test "its access point gives phones the box as DNS, and answers every name", %{box: vm} do
    {:ok, out} =
      Provision.VM.eval(vm, ~S[cfg = Application.fetch_env!(:firmware, :own_network); inspect({cfg.dnsd.records, cfg.dhcpd.options.dns}) |> IO.puts()])

    assert out =~ ~s({"*", {192, 168, 24, 1}}), "every name should resolve to the box"
    assert out =~ "[{192, 168, 24, 1}]", "phones should be handed the box as their DNS server"
  end

  test "a phone's first check gets the portal; after Continue it gets the answer iOS wants", %{box: vm} do
    # before: "there is a portal", so iOS opens its sheet on the Observatory
    {200, first} = get(vm, "/hotspot-detect.html")
    assert first =~ "Continue"
    refute first =~ "<BODY>Success</BODY>"
    assert {302, _} = get(vm, "/generate_204")

    # Continue, from the same address, as the phone would
    assert {302, _} = get(vm, "/portal/continue")

    # after: exactly what iOS and Android want, so the phone stays on the network
    assert {200, "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"} = get(vm, "/hotspot-detect.html")
    assert {204, _} = get(vm, "/generate_204")
  end

  defp get(vm, path) do
    {:ok, _} = Application.ensure_all_started(:inets)
    url = ~c"http://127.0.0.1:#{vm.web_port}#{path}"
    {:ok, {{_, status, _}, _, body}} = :httpc.request(:get, {url, []}, [timeout: 15_000, autoredirect: false], [])
    {status, to_string(body)}
  end

  defp body(vm, path), do: vm |> get(path) |> elem(1)

  # qemu's user networking cannot carry a ping in from outside, so this checks
  # the thing that decides it: the kernel answering ICMP echo at all.
  test "it answers ping", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, ~S[File.read!("/proc/sys/net/ipv4/icmp_echo_ignore_all") |> String.trim() |> IO.puts()])
    assert out =~ ~r/^0/m, "the box must not ignore pings; it is the first thing anyone tries"
  end

  test "it announces its page by name, so a phone can find it", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "Application.get_env(:mdns_lite, :services) |> Enum.map(& &1.port) |> inspect() |> IO.puts()")
    assert out =~ "80"
  end

  test "the mount driver comes up and finds no cable, so it simulates", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "Mount.list() |> Enum.map(& &1.id) |> inspect() |> IO.puts()")
    # there is no serial cable in a VM, so whatever is listed is a simulator or nothing
    assert out =~ "[" and out =~ "]"
  end

  test "networking is up", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, "VintageNet.get_configuration(\"eth0\") |> inspect() |> IO.puts()")
    assert out =~ "type" or out =~ "ipv4"
  end

  test "the filesystem is a real device filesystem, writable where it should be", %{box: vm} do
    {:ok, out} = Provision.VM.eval(vm, ~S[File.write("/root/loop-test", "hello") |> inspect() |> IO.puts()])
    assert out =~ ":ok"
    {:ok, back} = Provision.VM.eval(vm, ~S[File.read!("/root/loop-test") |> IO.puts()])
    assert back =~ "hello"
  end
end
