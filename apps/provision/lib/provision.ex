defmodule Provision do
  @moduledoc """
  Stamping a box: take a blank SSD or card, choose what the box is for, give
  it network credentials, and write a bootable Observatory onto it.

  This app knows three things and nothing else about the telescope: which
  removable disks are attached (`Provision.Disks`), what a box can be
  (`Provision.Templates`), and how to turn that into a written card
  (`Provision.Job`). It shells out to `fwup` and to the firmware project's
  own `mix firmware`; it never reaches into the mount, the camera or the UI.

  Everything it does is announced on the `"provision"` topic as
  `{:provision, status}`, so a page can show every step as it happens
  rather than a spinner and a shrug.

      Provision.subscribe()
      Provision.start(disk: "/dev/disk4", template: :observatory, target: :rpi4,
                      wifi: %{ssid: "Barn", psk: "…"}, hostname: "observatory")
  """

  defdelegate disks(), to: Provision.Disks, as: :list
  defdelegate templates(), to: Provision.Templates, as: :all
  defdelegate targets(), to: Provision.Templates, as: :targets

  defdelegate start(opts), to: Provision.Job
  defdelegate cancel(), to: Provision.Job
  defdelegate clear(), to: Provision.Job
  defdelegate status(), to: Provision.Job

  @doc "Every step, as it happens: `{:provision, status}` on this topic."
  def subscribe, do: Telescope.subscribe("provision")

  @doc """
  The Nerves project this machine builds images from.

  `__DIR__` is apps/provision/lib, so the root of the repo is three levels up.
  """
  def firmware_dir, do: Application.get_env(:provision, :firmware_dir) || Path.expand("../../../firmware", __DIR__)

  @doc """
  Can the command this page hands over actually run? Says plainly what is missing.

  The page does not build or write anything itself, but handing someone a
  command that is going to fail on a missing tool wastes their ten minutes just
  as surely. Each missing piece is named here, with the line that installs it.
  """
  def ready? do
    cond do
      is_nil(System.find_executable("fwup")) ->
        {:error, "fwup is not installed on this machine. brew install fwup, or apt install fwup."}

      is_nil(System.find_executable("mksquashfs")) ->
        {:error, "squashfs is not installed on this machine. brew install squashfs, or apt install squashfs-tools."}

      not File.dir?(firmware_dir()) ->
        {:error, "No firmware project at #{firmware_dir()}. Images are built from there."}

      not nerves_bootstrap?() ->
        {:error, "Nerves is not set up on this machine. mix archive.install hex nerves_bootstrap"}

      true ->
        :ok
    end
  end

  # Nerves puts its Mix tasks in an archive rather than a dependency, so the
  # build fails on the first task it cannot find unless we look first.
  defp nerves_bootstrap? do
    (System.get_env("MIX_HOME") || Path.expand("~/.mix"))
    |> Path.join("archives")
    |> File.ls()
    |> case do
      {:ok, entries} -> Enum.any?(entries, &String.starts_with?(&1, "nerves_bootstrap"))
      _ -> false
    end
  end
end
