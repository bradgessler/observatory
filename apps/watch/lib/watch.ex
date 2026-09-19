defmodule Watch do
  @moduledoc """
  A camera pointed at the hardware, read by the server.

      Watch.capture()      # grab a frame now
      Watch.enable(true)   # every few seconds
      Watch.latest()       # %{jpeg: ..., at: ..., device: ...} | nil
      Watch.subscribe()    # {:watch, %{at, device, bytes}} on every new frame
      Watch.history()      # recent frames on disk, newest first: %{name, at, bytes}
      Watch.frame(name)    # {:ok, jpeg} for one of them
  """

  def subscribe, do: Telescope.subscribe("watch")

  defdelegate history(opts \\ []), to: Watch.History, as: :list
  defdelegate frame(name), to: Watch.History, as: :read
  defdelegate history_summary, to: Watch.History, as: :summary

  defdelegate latest, to: Watch.Camera
  defdelegate status, to: Watch.Camera
  defdelegate capture, to: Watch.Camera
  defdelegate enable(on?), to: Watch.Camera
  defdelegate select(device), to: Watch.Camera
  defdelegate devices, to: Watch.Camera
end
