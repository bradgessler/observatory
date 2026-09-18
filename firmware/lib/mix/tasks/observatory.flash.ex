defmodule Mix.Tasks.Observatory.Flash do
  @shortdoc "Build the Pi image with your Wi-Fi baked in and burn it to an SD card"

  @moduledoc """
  The whole v1 loop in one command, run from `firmware/`:

      mix observatory.flash

  Asks for the Pi model and the Wi-Fi network (or takes them from
  `MIX_TARGET`, `WIFI_SSID`, `WIFI_PSK`), builds the firmware, then burns it
  to the SD card `fwup` finds. Afterwards: card into the Pi, Pi into the mount,
  power on, and it shows up as `telescope.local`.

  Options:

      --target rpi4        skip the model prompt (rpi0_2 | rpi3 | rpi3a | rpi4 | rpi5)
      --ssid NAME          skip the network prompts
      --psk SECRET
      --no-burn            build only (e.g. to `mix upload telescope.local` later)
      --upload HOST        build and push over the network instead of burning
  """
  use Mix.Task

  @targets ~w(rpi0_2 rpi3 rpi3a rpi4 rpi5)

  @impl true
  def run(argv) do
    {opts, _, _} =
      OptionParser.parse(argv,
        strict: [target: :string, ssid: :string, psk: :string, burn: :boolean, upload: :string]
      )

    target = opts[:target] || System.get_env("MIX_TARGET") || ask_target()
    ssid = opts[:ssid] || System.get_env("WIFI_SSID") || ask("Wi-Fi network name (blank to skip)")
    psk = if ssid != "", do: opts[:psk] || System.get_env("WIFI_PSK") || ask("Wi-Fi password", secret: true)

    env =
      [{"MIX_TARGET", target}, {"MIX_ENV", "prod"}] ++
        if(ssid != "", do: [{"WIFI_SSID", ssid}, {"WIFI_PSK", psk}], else: [])

    Mix.shell().info("\n→ building for #{target}#{if ssid != "", do: " with Wi-Fi \"#{ssid}\""}\n")
    mix!(["deps.get"], env)
    mix!(["firmware"], env)

    cond do
      host = opts[:upload] ->
        Mix.shell().info("\n→ uploading to #{host}\n")
        mix!(["upload", host], env)

      opts[:burn] == false ->
        Mix.shell().info("\nBuilt. Burn later with: MIX_TARGET=#{target} mix burn")

      true ->
        Mix.shell().info("\n→ burning (insert the SD card if you haven't)\n")
        mix!(["burn"], env)
        Mix.shell().info("\nDone. Card → Pi → mount's HAND CONTROL port → power. Then: ssh telescope.local")
    end
  end

  defp mix!(args, env) do
    case System.cmd("mix", args, env: env, into: IO.stream(:stdio, :line), stderr_to_stdout: true) do
      {_, 0} -> :ok
      {_, code} -> Mix.raise("mix #{Enum.join(args, " ")} failed (exit #{code})")
    end
  end

  defp ask_target do
    Mix.shell().info("Which Raspberry Pi?")
    Enum.with_index(@targets, 1) |> Enum.each(fn {t, i} -> Mix.shell().info("  #{i}) #{t}") end)

    case ask("Number or name") do
      n when n in ~w(1 2 3 4 5) -> Enum.at(@targets, String.to_integer(n) - 1)
      t when t in @targets -> t
      other -> Mix.raise("unknown target #{inspect(other)}; one of #{Enum.join(@targets, ", ")}")
    end
  end

  defp ask(prompt, opts \\ []) do
    answer =
      if opts[:secret] and IO.ANSI.enabled?() do
        # no echo where the terminal allows it
        IO.write("#{prompt}: ")
        pw = :io.get_password() |> to_string()
        IO.write("\n")
        pw
      else
        Mix.shell().prompt("#{prompt}:") |> to_string()
      end

    String.trim(answer)
  end
end
