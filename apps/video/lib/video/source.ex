defmodule Video.Source do
  @moduledoc """
  Where the pictures come from. A source turns a device choice and a size
  into FFmpeg *input* arguments, and says what the device can do. The
  encoder and the HLS muxer don't care.

  `Video.Source.Local` reads a camera attached to this machine. The next
  one is a remote source: a small node (a Pi) forwards a raw stream over
  TCP and the big node encodes it — same behaviour, different `input_args`.
  """

  @type mode :: {pos_integer, pos_integer}

  @doc "Cameras this source can see, as `%{id, name}`."
  @callback devices() :: [%{id: String.t(), name: String.t()}]

  @doc "Sizes a device supports, or `:unknown` when the platform can't say."
  @callback modes(device :: String.t() | nil) :: [mode] | :unknown

  @doc "FFmpeg arguments up to and including `-i …` for this device at this size."
  @callback input_args(device :: String.t() | nil, size :: mode) :: [String.t()]

  @doc "The source in use."
  def impl, do: Application.get_env(:video, :source, Video.Source.Local)
end
