defmodule Controller.Optical.Frame do
  @moduledoc """
  A camera frame as the axis finder sees it: grey, small, a flat binary.

  JPEG in via a tiny C decoder, then averaged down by an integer factor so a
  1280×720 still becomes 320×180 — plenty to see a tube move, cheap enough
  to do in plain Elixir. `%{w, h, pixels, scale}`; `scale` maps back to the
  original image for drawing.
  """

  @type t :: %{w: pos_integer, h: pos_integer, pixels: binary, scale: pos_integer}

  @doc "Load a JPEG/PNG file, grey, downsampled by `factor` (default 4)."
  def load(path, factor \\ 4) do
    with {:ok, img} <- StbImage.read_file(path), do: {:ok, from_image(img, factor)}
  end

  @doc "Same, from the bytes of a JPEG."
  def from_binary(bin, factor \\ 4) do
    with {:ok, img} <- StbImage.read_binary(bin), do: {:ok, from_image(img, factor)}
  end

  def from_image(%StbImage{shape: {h, w, ch}, data: data}, factor) do
    grey = to_grey(data, ch)
    downsample(%{w: w, h: h, pixels: grey}, factor)
  end

  @doc "Build a frame from a grey binary (tests, synthetic scenes)."
  def from_grey(w, h, pixels, scale \\ 1) when byte_size(pixels) == w * h, do: %{w: w, h: h, pixels: pixels, scale: scale}

  @doc "Pixel value at column x, row y (0 outside)."
  def at(%{w: w, h: h, pixels: px}, x, y) when x >= 0 and y >= 0 and x < w and y < h, do: :binary.at(px, y * w + x)
  def at(_, _, _), do: 0

  # luma the cheap way; integer maths, one pass
  defp to_grey(data, 3), do: for(<<r, g, b <- data>>, into: <<>>, do: <<div(r * 77 + g * 150 + b * 29, 256)>>)
  defp to_grey(data, 4), do: for(<<r, g, b, _a <- data>>, into: <<>>, do: <<div(r * 77 + g * 150 + b * 29, 256)>>)
  defp to_grey(data, 1), do: data
  defp to_grey(data, 2), do: for(<<g, _a <- data>>, into: <<>>, do: <<g>>)

  # average factor×factor blocks; rows are processed as binaries, columns summed in chunks
  defp downsample(%{w: w, h: h, pixels: px}, 1), do: %{w: w, h: h, pixels: px, scale: 1}

  defp downsample(%{w: w, h: h, pixels: px}, f) do
    ow = div(w, f)
    oh = div(h, f)
    n = f * f

    rows =
      for oy <- 0..(oh - 1) do
        # sum the f source rows column-wise into a list of ints, then bucket by f
        sums =
          Enum.reduce(0..(f - 1), List.duplicate(0, ow * f), fn dy, acc ->
            row = binary_part(px, (oy * f + dy) * w, ow * f)
            Enum.zip_with(acc, :binary.bin_to_list(row), &+/2)
          end)

        sums
        |> Enum.chunk_every(f)
        |> Enum.map(fn chunk -> div(Enum.sum(chunk), n) end)
        |> :binary.list_to_bin()
      end

    %{w: ow, h: oh, pixels: IO.iodata_to_binary(rows), scale: f}
  end
end
