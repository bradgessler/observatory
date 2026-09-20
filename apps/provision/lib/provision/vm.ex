defmodule Provision.VM do
  @moduledoc """
  The same image, booted on this machine instead of a Pi.

  A card swap is a two minute round trip and you cannot put a test around it.
  The `x86_64` Nerves target produces a real image, made by the same `fwup`
  that writes a card, holding the same rootfs and the same release. Applied to
  a file instead of a disk and handed to QEMU, it boots in about forty
  seconds, brings up networking, and answers on SSH. So a change can be built,
  booted and asserted on in a loop, with no hardware involved.

  What it does prove: the image is bootable, the release starts, the
  supervision tree comes up, networking works, and any app in the firmware
  behaves on a real device filesystem.

  What it cannot prove: anything about the Pi itself. No EQDIR cable, no
  camera, no GPIO, and no ARM. Those still need the real box; this is the loop
  you run a hundred times a day so that the real box only has to be right
  about hardware.

      {:ok, vm} = Provision.VM.boot()
      {:ok, "29"} = Provision.VM.eval(vm, ":erlang.system_info(:otp_release)")
      Provision.VM.stop(vm)
  """

  @banner ~r/Nerves CLI help|Toolshed.* imported|iex\(\d+\)>/
  @default_ssh 4422
  @default_web 4444

  @doc """
  Build the image, if it is not built already, and hand back the path to a
  disk image QEMU can boot. `fwup` writing to a file is the same code path
  that writes a card, so this exercises it too.
  """
  def image(opts \\ []) do
    fw = opts[:fw] || firmware_path()
    out = opts[:out] || Path.join(System.tmp_dir!(), "observatory-vm.img")

    cond do
      is_nil(fw) or not File.exists?(fw) ->
        {:error, "No x86_64 firmware built yet. Run: cd firmware && MIX_TARGET=x86_64 MIX_ENV=prod mix firmware"}

      not stale?(fw, out) ->
        {:ok, out}

      true ->
        File.rm_rf(out)

        case System.cmd("fwup", ["-a", "-i", fw, "-d", out, "-t", "complete", "-q"], stderr_to_stdout: true) do
          {_, 0} -> {:ok, out}
          {err, code} -> {:error, "fwup failed (#{code}): #{String.slice(err, 0, 300)}"}
        end
    end
  end

  defp stale?(fw, img) do
    not File.exists?(img) or File.stat!(fw).mtime > File.stat!(img).mtime
  end

  @doc """
  Boot the image and wait until it is up. Returns a handle holding the port,
  the forwarded ports and everything the console said, so a failed boot can be
  read rather than guessed at.
  """
  def boot(opts \\ []) do
    ssh = opts[:ssh_port] || @default_ssh
    web = opts[:web_port] || @default_web
    wait = opts[:timeout] || 90_000

    with {:ok, img} <- image(opts) do
      args = [
        "-m", to_string(opts[:memory] || 1024),
        "-smp", to_string(opts[:cpus] || 2),
        "-drive", "file=#{img},format=raw,if=virtio",
        "-netdev", "user,id=n0,hostfwd=tcp::#{ssh}-:22,hostfwd=tcp::#{web}-:4000",
        "-device", "virtio-net-pci,netdev=n0",
        # stdio is the serial console and nothing else: with the monitor
        # multiplexed onto it, a port with no terminal can wedge at boot
        "-display", "none",
        "-monitor", "none",
        "-serial", "stdio"
      ]

      exe = System.find_executable("qemu-system-x86_64")

      if is_nil(exe) do
        {:error, "qemu-system-x86_64 is not installed. brew install qemu."}
      else
        port = Port.open({:spawn_executable, exe}, [:binary, :exit_status, {:args, args}, :hide])
        # keep the operating system's pid: a closed port does not always take
        # qemu with it, and a stray VM holds the forwarded ports
        os_pid = case :erlang.port_info(port, :os_pid) do
          {:os_pid, pid} -> pid
          _ -> nil
        end

        vm = %{port: port, os_pid: os_pid, ssh_port: ssh, web_port: web, image: img, console: []}

        with {:ok, vm} <- wait_ready(vm, wait) |> unwrap(),
             :ok <- wait_ssh(vm, opts[:ssh_timeout] || 60_000) do
          {:ok, vm}
        else
          {:error, why, vm} -> stop(vm); {:error, why}
          {:error, why} -> stop(vm); {:error, why}
        end
      end
    end
  end

  defp unwrap({:ok, vm}), do: {:ok, vm}
  defp unwrap(other), do: other

  @doc """
  The banner means IEx is up, which is not the same as sshd being up: the
  services on a booting box come good in their own order. So ask until it
  answers rather than assuming.
  """
  def wait_ssh(vm, timeout \\ 60_000) do
    deadline = System.monotonic_time(:millisecond) + timeout
    try_ssh(vm, deadline)
  end

  defp try_ssh(vm, deadline) do
    case eval(vm, ":ok |> IO.inspect()", timeout: 8_000) do
      {:ok, _} ->
        :ok

      {:error, why} ->
        if System.monotonic_time(:millisecond) > deadline do
          {:error, "The image booted but ssh never answered: #{why}"}
        else
          Process.sleep(2_000)
          try_ssh(vm, deadline)
        end
    end
  end

  @doc "Wait for the image to finish booting, collecting the console as it goes."
  def wait_ready(vm, timeout \\ 120_000) do
    deadline = System.monotonic_time(:millisecond) + timeout
    collect(vm, deadline)
  end

  defp collect(vm, deadline) do
    left = deadline - System.monotonic_time(:millisecond)

    if left <= 0 do
      {:error, "The image did not finish booting in time.\n#{console(vm)}", vm}
    else
      port = vm.port

      receive do
        {^port, {:data, chunk}} ->
          vm = %{vm | console: [chunk | vm.console]}
          if Regex.match?(@banner, chunk), do: {:ok, vm}, else: collect(vm, deadline)

        {^port, {:exit_status, code}} ->
          {:error, "QEMU stopped before the image booted (#{code}).\n#{console(vm)}", vm}
      after
        left -> {:error, "The image did not finish booting in time.\n#{console(vm)}", vm}
      end
    end
  end

  @doc """
  Run Elixir on the booted image and hand back what it printed.

  This is the whole point of the loop: an assertion can ask the running system
  a question, rather than a person reading a console and deciding.
  """
  def eval(vm, code, opts \\ []) do
    args = [
      "-p", to_string(vm.ssh_port),
      "-o", "StrictHostKeyChecking=no",
      "-o", "UserKnownHostsFile=/dev/null",
      "-o", "LogLevel=ERROR",
      "-o", "BatchMode=yes",
      "-o", "ConnectTimeout=#{div(opts[:timeout] || 15_000, 1000)}",
      "nerves@localhost",
      code
    ]

    case System.cmd("ssh", args, stderr_to_stdout: true) do
      {out, 0} -> {:ok, out |> String.replace(~r/\r/, "") |> String.trim()}
      {out, code} -> {:error, "ssh exited #{code}: #{String.trim(out)}"}
    end
  end

  @doc "Everything the console has said, oldest first."
  def console(vm), do: vm.console |> Enum.reverse() |> Enum.join()

  @doc "Shut the machine down."
  def stop(vm) do
    if is_port(vm.port) do
      try do
        Port.close(vm.port)
      rescue
        _ -> :ok
      end
    end

    if vm[:os_pid], do: System.cmd("kill", ["-9", to_string(vm.os_pid)], stderr_to_stdout: true)
    :ok
  end

  defp firmware_path do
    [
      Path.expand("../../../../firmware/_build/x86_64_prod/nerves/images/firmware.fw", __DIR__),
      Path.expand("../../../../firmware/_build/x86_64_dev/nerves/images/firmware.fw", __DIR__)
    ]
    |> Enum.find(&File.exists?/1)
  end
end
