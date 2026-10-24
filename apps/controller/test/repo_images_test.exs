defmodule Controller.RepoImagesTest do
  @moduledoc """
  The repository is public, so what's in it is published. 23 October 2026, Brad: "I don't want to commit a bunch of
  images with metadata in the Git repo." Every image in git carries no metadata at all (no EXIF, XMP, ICC, comments,
  PNG text chunks: a camera's JPEG brings its serial and settings along, and a stack's FITS would bring the site),
  and the heavy formats that hold metadata by design (FITS, TIFF, XISF, RAW, NumPy) are never committed: they live
  with the night's files under ~/.observatory.
  """
  use ExUnit.Case, async: true

  @root Path.expand("../../..", __DIR__)
  @heavy ~w(.fits .fit .fts .tif .tiff .xisf .arw .cr2 .cr3 .nef .dng .npz .npy)

  defp tracked do
    {out, 0} = System.cmd("git", ["ls-files"], cd: @root)
    String.split(out, "\n", trim: true)
  end

  test "no file in git is a format that carries metadata by design" do
    assert Enum.filter(tracked(), &(Path.extname(&1) |> String.downcase() |> then(fn e -> e in @heavy end))) == []
  end

  test "no image in git carries metadata" do
    images = Enum.filter(tracked(), &(Path.extname(&1) |> String.downcase() |> then(fn e -> e in ~w(.jpg .jpeg .png) end)))
    assert images != []
    carrying = for f <- images, kinds = metadata(File.read!(Path.join(@root, f))), kinds != [], do: {f, kinds}
    assert carrying == [], "these images carry metadata; strip it (image data untouched) before committing: #{inspect(carrying)}"
  end

  # JPEG: APP1..APP15 (EXIF, XMP, ICC, maker data) and COM segments before the scan
  defp metadata(<<0xFF, 0xD8, rest::binary>>), do: jpeg(rest, [])
  # PNG: text, EXIF and time chunks
  defp metadata(<<0x89, "PNG\r\n", 0x1A, "\n", rest::binary>>), do: png(rest, [])
  defp metadata(_), do: []

  defp jpeg(<<0xFF, 0xDA, _::binary>>, acc), do: acc
  defp jpeg(<<0xFF, m, len::16, rest::binary>>, acc) when len >= 2 and byte_size(rest) >= len - 2 do
    <<_::binary-size(len - 2), more::binary>> = rest
    jpeg(more, if((m >= 0xE1 and m <= 0xEF) or m == 0xFE, do: [m | acc], else: acc))
  end

  defp jpeg(_, acc), do: acc

  defp png(<<len::32, type::binary-size(4), rest::binary>>, acc) when byte_size(rest) >= len + 4 do
    <<_::binary-size(len), _crc::32, more::binary>> = rest
    acc = if type in ~w(tEXt zTXt iTXt eXIf tIME), do: [type | acc], else: acc
    if type == "IEND", do: acc, else: png(more, acc)
  end

  defp png(_, acc), do: acc
end
