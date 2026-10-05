defmodule Camera do
  @moduledoc """
  Stills cameras driven over USB with PTP: the Sony a6000 and its generation
  in PC Remote mode (`Camera.Sony`), found and supervised by
  `Camera.Discovery`, one `Camera.Server` each.

      Camera.list()                                   # what's plugged in, and its settings
      Camera.set("sony-ilce-6000", iso: 800, shutter: "1/60")
      {:ok, files} = Camera.capture("sony-ilce-6000") # [%{name, format, bytes, info}]

  Every knob is a parameter here, so a page, an agent or IEx drives it the
  same way. State is broadcast on `"cameras"` and `"camera:<id>"`: a real
  camera's to every machine in the cluster, a simulated one's to this
  machine only (`Telescope.listed?/3`).
  """

  defdelegate list, to: Camera.Discovery
  defdelegate seen, to: Camera.Discovery
  defdelegate status(id), to: Camera.Server
  defdelegate set(id, settings), to: Camera.Server
  defdelegate capture(id, opts \\ []), to: Camera.Server

  @doc "Is this a simulated camera? Its status says so (`sim: true`). One rule, so no page invents its own."
  def simulated?(%{sim: true}), do: true
  def simulated?(_), do: false

  @doc "Follow every camera: `{:camera, status}` messages."
  def subscribe, do: Telescope.subscribe("cameras")

  @doc "Follow one camera."
  def subscribe(id), do: Telescope.subscribe("camera:" <> id)
end
