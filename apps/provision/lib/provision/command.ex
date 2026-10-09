defmodule Provision.Command do
  @moduledoc """
  The choices from the five screens, written out as the command that makes the
  card.

  Writing to a raw disk is root's work, and a web page is the wrong place to
  ask for a password: the browser would have to carry it, the server would have
  to hold it, and the machine would have to keep a standing grant afterwards.
  A terminal already does this properly — it asks once, for one command, and
  keeps nothing.

  So the page does the part it is good at (choosing, and saying what each
  choice means) and hands over one line to run. Nothing here touches hardware;
  it is a pure function of the choices, which is what makes it testable.
  """

  @doc """
  The command for these choices, as

      %{lines: ["cd firmware", "export …", "mix observatory.flash --target rpi4"],
        note: "It will ask for your password…", os: :macos}

  `os` is `:os.type()` by default; pass one to render for another machine.
  """
  def build(opts, os \\ :os.type()) do
    env = Provision.Templates.build_env(opts)
    target = env["MIX_TARGET"]

    %{
      lines: ["cd firmware"] ++ exports(env) ++ ["mix observatory.flash --target #{target}"],
      note: note(kind(os)),
      os: kind(os)
    }
  end

  @doc "The command as one block of text, which is what a person copies."
  def text(opts, os \\ :os.type()), do: build(opts, os).lines |> Enum.join("\n")

  # MIX_TARGET and MIX_ENV are said by the task itself; everything else is
  # read by the firmware build and has to be in the environment around it.
  # WIFI_SSID is always exported, empty included: left unset, the task stops
  # and asks, and a command that asks questions is not one you can paste.
  defp exports(env) do
    env
    |> Map.drop(["MIX_TARGET", "MIX_ENV"])
    |> Map.put_new("WIFI_SSID", "")
    |> Map.put_new("WIFI_PSK", "")
    |> Enum.sort()
    |> Enum.map(fn {k, v} -> "export #{k}=#{quote_arg(v)}" end)
  end

  @doc """
  A value made safe to put after `=` or on a command line. A network called
  Bob's Barn is a perfectly ordinary name and would otherwise end the string
  early.
  """
  def quote_arg(""), do: "''"

  def quote_arg(v) do
    if String.match?(v, ~r/\A[A-Za-z0-9_.,:\/@%+-]+\z/) do
      v
    else
      "'" <> String.replace(v, "'", "'\\''") <> "'"
    end
  end

  defp kind({:unix, :darwin}), do: :macos
  defp kind({:unix, _}), do: :linux
  defp kind(_), do: :other

  defp note(:macos),
    do: "It asks for your password when it gets to the card: writing to a disk needs administrator rights on a Mac."

  defp note(:linux),
    do: "Run it with sudo if it says permission denied: writing to a disk needs root unless your user is in the disk group."

  defp note(_), do: "Writing to a card needs administrator rights."
end
