defmodule Video do
  @moduledoc """
  Live video of the hardware as HLS, produced by FFmpeg under a BEAM port and
  served as plain files. Safari plays HLS natively; other browsers get hls.js.

      Video.start(quality: :"1k", fps: 30)   # begin encoding; ready a few seconds later
      Video.stop()
      Video.status()                # %{state, quality, ready, playlist, ...}
      Video.qualities()             # the ladder, with what this camera can do
      Video.snapshot()              # {:ok, jpeg} — a still the encoder writes every few seconds
      Video.subscribe()             # {:video, status} on every change

  This is a *workload*, deliberately separate from `Watch` (stills). It is
  the heavy thing: it should run on the node with the most CPU, which is not
  always the node with the camera. `Video.Source` is the seam: today
  `Video.Source.Local` reads a camera on this machine; a remote source that
  takes a raw stream forwarded from a small node plugs in the same way.
  """

  def subscribe, do: Telescope.subscribe("video")

  defdelegate start(opts \\ []), to: Video.HLS
  defdelegate stop, to: Video.HLS
  defdelegate status, to: Video.HLS
  defdelegate qualities, to: Video.HLS
  defdelegate snapshot, to: Video.HLS
  defdelegate select(device), to: Video.HLS
end
