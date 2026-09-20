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
  defdelegate status(), to: Provision.Job

  @doc "Every step, as it happens: `{:provision, status}` on this topic."
  def subscribe, do: Telescope.subscribe("provision")

  @doc "Can this machine write a card at all? Says plainly what is missing."
  def ready? do
    cond do
      is_nil(System.find_executable("fwup")) ->
        {:error, "fwup is not installed on this machine. brew install fwup, or apt install fwup."}

      true ->
        :ok
    end
  end
end
