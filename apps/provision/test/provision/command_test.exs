defmodule Provision.CommandTest do
  @moduledoc """
  The command the page hands over. It is pasted into a terminal by someone who
  cannot see what we meant, so it has to be right on its own.
  """
  use ExUnit.Case, async: true

  @mac {:unix, :darwin}
  @linux {:unix, :linux}

  defp opts(extra \\ []) do
    Keyword.merge(
      [template: :observatory, target: :rpi4, flavour: :prod, hostname: "observatory", wifi: %{ssid: "", psk: ""}],
      extra
    )
  end

  test "it runs from the firmware project and names the machine it is for" do
    text = Provision.Command.text(opts(target: :rpi5), @mac)

    assert text =~ "cd firmware"
    assert text =~ "mix observatory.flash --target rpi5"
  end

  test "the choices ride along as environment the build reads" do
    text = Provision.Command.text(opts(template: :mount_only, hostname: "barn", flavour: :dev), @mac)

    assert text =~ "export OBS_TEMPLATE=mount_only"
    assert text =~ "export NERVES_HOSTNAME=barn"
    assert text =~ "export OBS_FLAVOUR=dev"
    assert text =~ "export OBS_AP_SSID=barn"
    refute text =~ "setup"
  end

  test "a network whose name would end the string early is quoted" do
    text = Provision.Command.text(opts(wifi: %{ssid: "Bob's Barn", psk: "a b"}), @mac)

    assert text =~ ~S(export WIFI_SSID='Bob'\''s Barn')
    assert text =~ ~S(export WIFI_PSK='a b')
  end

  test "with no Wi-Fi it still says so, because a blank stops the task asking" do
    text = Provision.Command.text(opts(), @mac)

    # left unset the task prompts, and a command that asks questions is not one
    # you can paste
    assert text =~ "export WIFI_SSID=''"
  end

  test "it says how each machine asks for the rights writing a card needs" do
    assert Provision.Command.build(opts(), @mac).note =~ "password"
    assert Provision.Command.build(opts(), @linux).note =~ "sudo"
    assert Provision.Command.build(opts(), @mac).os == :macos
    assert Provision.Command.build(opts(), @linux).os == :linux
  end

  test "the command is the last line, so it reads as one thing to run" do
    lines = Provision.Command.build(opts(), @mac).lines

    assert List.last(lines) =~ "mix observatory.flash"
    assert hd(lines) == "cd firmware"
  end
end
