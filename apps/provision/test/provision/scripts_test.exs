defmodule Provision.ScriptsTest do
  @moduledoc """
  The saved script is the thing a person runs with their password, so what it
  does as root is the part worth pinning down.
  """
  use ExUnit.Case, async: false

  defp opts(extra \\ []) do
    Keyword.merge(
      [template: :observatory, target: :rpi3, flavour: :dev, hostname: "barn", wifi: %{ssid: "Bob's Barn", psk: "hunter2"}],
      extra
    )
  end

  test "only the write runs as root, and it names no disk" do
    lines = Provision.Scripts.render(opts()) |> String.split("\n") |> Enum.reject(&(String.trim_leading(&1) =~ ~r/^(#|echo |printf )/))
    root = Enum.filter(lines, &String.contains?(&1, "sudo "))

    # one line, fwup; the builds run as you, or _build ends up owned by root
    assert [write] = root
    assert write =~ "fwup"

    # no -d: fwup finds the card that is plugged in and asks first, where a
    # disk number saved last week could name something else entirely
    refute write =~ " -d "
  end

  test "it goes to the firmware project and builds for the machine chosen" do
    text = Provision.Scripts.render(opts())

    assert text =~ "cd " <> Provision.firmware_dir()
    assert text =~ "export MIX_TARGET=rpi3"
    assert text =~ "mix firmware"
    assert text =~ ~S(export WIFI_SSID='Bob'\''s Barn')
  end

  test "one build, then as many cards as you feed it" do
    text = Provision.Scripts.render(opts())
    [build, write] = String.split(text, "while :; do")

    assert build =~ "mix firmware"
    refute write =~ "mix firmware", "the loop must not rebuild for every card"
    assert write =~ ~r/sudo .*fwup/
    # an eject stops some readers until they are replugged, so the next card
    # in the loop would never show up
    assert write =~ "--no-eject"
  end

  test "it says the write needs your password before sudo asks, and sudo says what for" do
    text = Provision.Scripts.render(opts())
    [build, write] = String.split(text, "mix deps.get")

    # said before the build, which runs for minutes before the prompt appears
    assert build =~ ~r/^echo .*sudo will ask for your password/m
    # sudo's own prompt names the account and the job, not a bare "Password:"
    assert write =~ ~S(sudo -p "sudo password for %u@%h, to write the SD card: " fwup)
  end

  test "it unmounts the card fwup found, and only that card, before writing" do
    [_build, write] = String.split(Provision.Scripts.render(opts()), "while :; do")
    [before_write | _] = String.split(write, "fwup -a")

    # the device fwup detects, not a disk number and not every external disk
    assert before_write =~ "fwup --detect"
    assert before_write =~ ~S(diskutil unmountDisk "${card#/dev/r}")
    refute before_write =~ "external"
  end

  test "it is a script the shell can actually run" do
    path = Path.join(System.tmp_dir!(), "stamp-#{System.unique_integer([:positive])}.sh")
    File.write!(path, Provision.Scripts.render(opts()))
    on_exit(fn -> File.rm(path) end)

    # parse only: a syntax error here would surface with a card in hand
    assert {_, 0} = System.cmd("sh", ["-n", path], stderr_to_stdout: true)
  end

  test "it stops at the first thing that fails" do
    # without set -e a failed build would carry on to sudo and write whatever
    # old image was lying in _build
    assert Provision.Scripts.render(opts()) =~ "\nset -e\n"
  end

  test "the second line says what it makes, for the list on the page" do
    [_shebang, about | _] = Provision.Scripts.render(opts()) |> String.split("\n")
    assert about =~ "Pi 3"
  end
end
