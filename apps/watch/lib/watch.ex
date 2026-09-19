defmodule Watch do
  @moduledoc """
  A camera pointed at the hardware, read by the server.

      Watch.capture()      # grab a frame now
      Watch.enable(true)   # every few seconds
      Watch.latest()       # %{jpeg: ..., at: ..., device: ...} | nil
      Watch.subscribe()    # {:watch, %{at, device, bytes}} on every new frame
  """

  def subscribe, do: Telescope.subscribe("watch")

  defdelegate latest, to: Watch.Camera
  defdelegate status, to: Watch.Camera
  defdelegate capture, to: Watch.Camera
  defdelegate enable(on?), to: Watch.Camera
  defdelegate select(device), to: Watch.Camera
  defdelegate devices, to: Watch.Camera
end
