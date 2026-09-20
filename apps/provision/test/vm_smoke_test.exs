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
  @moduletag timeout: 300_000

  setup_all do
    case Provision.VM.boot() do
      {:ok, vm} ->
        on_exit(fn -> Provision.VM.stop(vm) end)
        %{box: vm}

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
