defmodule Provision.Scripts do
  @moduledoc """
  A stamp, saved as the shell script that makes it.

  The five screens are a script builder. What they build is written to
  `~/.observatory/stamps/<name>-<machine>.sh`, and from then on stamping
  another card is: put it in, run the script. The file is the saved
  configuration, readable and runnable with or without this page.

  Only the last line runs as root. Building as root would leave files in
  `_build` that the next build, run as you, cannot overwrite; so the script
  runs as you and asks sudo for the one thing that needs it. fwup is not told
  which disk to use: it finds the card that is plugged in and asks before it
  writes, which a disk number saved last week could not do safely.

  The Wi-Fi password is in the file, so the file and its folder are readable
  by you alone.
  """

  alias Provision.{Command, Templates}

  def dir, do: Application.get_env(:provision, :scripts_dir) || Path.join([System.user_home!(), ".observatory", "stamps"])

  @doc "Write the script for these choices. Returns its path."
  def save(opts) do
    File.mkdir_p!(dir())
    File.chmod!(dir(), 0o700)

    path = Path.join(dir(), file_name(opts))
    File.write!(path, render(opts))
    File.chmod!(path, 0o700)
    path
  end

  @doc "The saved scripts, newest first, as `%{name:, path:, about:}`."
  def list do
    case File.ls(dir()) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".sh"))
        |> Enum.map(&Path.join(dir(), &1))
        |> Enum.map(&describe/1)
        |> Enum.sort_by(& &1.modified, :desc)

      _ ->
        []
    end
  end

  @doc "The script's text for these choices."
  def render(opts) do
    env = Templates.build_env(opts) |> Map.put_new("WIFI_SSID", "") |> Map.put_new("WIFI_PSK", "")

    exports =
      [{"MIX_TARGET", env["MIX_TARGET"]}, {"MIX_ENV", env["MIX_ENV"]}] ++
        (env |> Map.drop(["MIX_TARGET", "MIX_ENV"]) |> Enum.sort())

    Enum.join(
      [
        "#!/bin/sh",
        "# " <> about(opts),
        "# Saved by Stamp a Box. Put a card in, then run: sh #{file_name(opts)}",
        "set -e",
        "",
        "cd #{Command.quote_arg(Provision.firmware_dir())}",
        Enum.map_join(exports, "\n", fn {k, v} -> "export #{k}=#{Command.quote_arg(v)}" end),
        "",
        # the page's terminal shows pages of mix output before the write, and
        # sudo's own prompt is a bare "Password:" that reads like Elixir asking
        "echo 'Building the firmware, then writing the SD card. The write needs root, so sudo will ask for your password.'",
        "",
        "mix deps.get",
        "mix firmware",
        "",
        "# Built once; written to as many SD cards as you feed it. Only the write",
        "# needs root. fwup finds the card and asks before writing; sudo remembers",
        "# your password for a few minutes, so the next cards usually do not ask.",
        ~S(fw="_build/${MIX_TARGET}_${MIX_ENV}/nerves/images/firmware.fw"),
        "while :; do",
        "  # --no-eject: an eject stops some USB readers' drives until they are",
        "  # unplugged, and then the next card never shows up. Unmounting is enough",
        "  # to pull the card safely.",
        "  # macOS mounts a card's partitions the moment it is inserted, and fwup",
        "  # refuses a disk it cannot unmount (\"unmount failed: 0xc010\"). Unmount",
        "  # the one card fwup finds, and nothing else, first; fwup still asks.",
        ~S'  card=$(fwup --detect 2>/dev/null | head -n 1 | cut -d, -f1)',
        ~S'  if [ -n "$card" ] && command -v diskutil >/dev/null; then diskutil unmountDisk "${card#/dev/r}" >/dev/null 2>&1 || true; fi',
        "  # the prompt says whose password and what for: user@host, the SD card",
        ~S(  if sudo -p "sudo password for %u@%h, to write the SD card: " fwup -a -i "$fw" -t complete --no-eject; then),
        ~S(    for v in /Volumes/BOOT-A /Volumes/BOOT-B /Volumes/AUTOBOOT; do [ -d "$v" ] && diskutil unmount "$v" >/dev/null 2>&1 || true; done),
        "    printf '\\nWritten. Insert the next SD card and press Enter (Ctrl-C to stop). '",
        "  else",
        "    printf '\\nNothing written. Insert an SD card and press Enter (Ctrl-C to stop). '",
        "  fi",
        "  read -r _ || exit 0",
        "done",
        ""
      ],
      "\n"
    )
  end

  @doc """
  The choices a saved script was made from, read back out of its exports, so
  the page can start the next stamp where the last one left off. Only values
  the page itself offers are accepted back: a script is a file anyone can edit.
  """
  def load(path) do
    with {:ok, text} <- File.read(path) do
      env =
        for line <- String.split(text, "\n"),
            [_, k, v] <- [Regex.run(~r/^export ([A-Z_]+)=(.*)$/, line)],
            into: %{},
            do: {k, unquote_arg(v)}

      {:ok, from_env(env)}
    end
  end

  defp from_env(env) do
    [
      template: known(env["OBS_TEMPLATE"], Enum.map(Templates.all(), & &1.id)),
      target: known(env["MIX_TARGET"], Enum.map(Templates.targets(), & &1.id)),
      flavour: known(env["OBS_FLAVOUR"], Enum.map(Templates.flavours(), & &1.id)),
      hostname: env["NERVES_HOSTNAME"],
      ap_ssid: env["OBS_AP_SSID"],
      ap_psk: env["OBS_AP_PSK"],
      wifi: %{ssid: env["WIFI_SSID"] || "", psk: env["WIFI_PSK"] || ""}
    ]
    |> Enum.reject(fn {_, v} -> is_nil(v) end)
  end

  defp known(nil, _ids), do: nil
  defp known(value, ids), do: Enum.find(ids, &(to_string(&1) == value))

  # the inverse of Command.quote_arg/1: '...' with each ' written as '\''
  defp unquote_arg("'" <> _ = v), do: v |> String.slice(1..-2//1) |> String.replace("'\\''", "'")
  defp unquote_arg(v), do: v

  @doc """
  A password for the box's own network, for when none is given: eight letters
  and digits in two groups, none of them easy to misread (no 0/O, 1/l/I), since
  it gets typed on a phone in the dark.
  """
  def suggest_password do
    alphabet = ~c"abcdefghjkmnpqrstuvwxyz23456789"
    pick = fn -> for _ <- 1..4, into: "", do: <<Enum.random(alphabet)>> end
    pick.() <> "-" <> pick.()
  end

  @doc "The name a script is saved under: the box's name and the machine it is for."
  def file_name(opts) do
    name = (opts[:hostname] || "observatory") |> String.downcase() |> String.replace(~r/[^a-z0-9-]+/, "-")
    "#{name}-#{opts[:target] || :rpi4}.sh"
  end

  defp about(opts) do
    plan = Templates.describe(opts)
    "#{plan.template} on a #{plan.target}. #{plan.flavour}. #{plan.network}."
  end

  defp describe(path) do
    about =
      case File.read(path) do
        {:ok, text} ->
          text |> String.split("\n") |> Enum.at(1, "") |> String.trim_leading("#") |> String.trim()

        _ ->
          ""
      end

    modified =
      case File.stat(path, time: :posix) do
        {:ok, %{mtime: t}} -> t
        _ -> 0
      end

    %{name: Path.basename(path), path: path, about: about, modified: modified}
  end
end
