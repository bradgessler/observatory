defmodule Controller.Test.Jpeg do
  @moduledoc """
  Tiny JPEGs with the EXIF a phone writes, for tests: enough for
  `Controller.Sky.Photo` to read a size and a shutter time. Options:
  `endian:` (:little), `original:` ("2026:09:25 21:14:03"), `offset:`
  ("-07:00", nil for none), `subsec:` ("123", nil for none).

      Jpeg.jpeg(original: "2026:09:25 21:14:03", offset: "+00:00")
  """

  # A JPEG as an iPhone writes one, cut to the bones: SOI, an Exif APP1 whose
  # Exif IFD carries DateTimeOriginal, OffsetTimeOriginal and
  # SubSecTimeOriginal, a start-of-frame with the size, EOI.
  def jpeg(opts \\ []) do
    endian = Keyword.get(opts, :endian, :little)
    original = Keyword.get(opts, :original, "2026:09:25 21:14:03")
    offset = Keyword.get(opts, :offset, "-07:00")
    subsec = Keyword.get(opts, :subsec, "123")

    u16 = fn n -> if endian == :little, do: <<n::little-16>>, else: <<n::big-16>> end
    u32 = fn n -> if endian == :little, do: <<n::little-32>>, else: <<n::big-32>> end
    entry = fn tag, type, count, value -> u16.(tag) <> u16.(type) <> u32.(count) <> value end

    # layout: header 8, IFD0 at 8 (1 entry: 2 + 12 + 4 = 18), Exif IFD at 26, then its strings
    exif_at = 26
    tags = [{0x9003, original <> <<0>>}, {0x9011, offset && offset <> <<0>>}, {0x9291, subsec && subsec <> <<0>>}] |> Enum.reject(&is_nil(elem(&1, 1)))
    data_at = exif_at + 2 + length(tags) * 12 + 4

    {entries, data, _} =
      Enum.reduce(tags, {<<>>, <<>>, data_at}, fn {tag, str}, {es, ds, at} ->
        if byte_size(str) <= 4 do
          {es <> entry.(tag, 2, byte_size(str), String.pad_trailing(str, 4, <<0>>)), ds, at}
        else
          {es <> entry.(tag, 2, byte_size(str), u32.(at)), ds <> str, at + byte_size(str)}
        end
      end)

    tiff =
      if(endian == :little, do: "II" <> <<42::little-16>>, else: "MM" <> <<42::big-16>>) <>
        u32.(8) <>
        u16.(1) <> entry.(0x8769, 4, 1, u32.(exif_at)) <> u32.(0) <>
        u16.(length(tags)) <> entries <> u32.(0) <> data

    app1 = "Exif" <> <<0, 0>> <> tiff
    sof = <<8, 3024::16, 4032::16, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1>>

    <<0xFF, 0xD8>> <>
      <<0xFF, 0xE1, byte_size(app1) + 2::16>> <> app1 <>
      <<0xFF, 0xC0, byte_size(sof) + 2::16>> <> sof <> <<0xFF, 0xD9>>
  end

  @doc "The EXIF fields for a UTC moment, as `jpeg/1` takes them."
  def at(%DateTime{} = t) do
    [original: Calendar.strftime(t, "%Y:%m:%d %H:%M:%S"), offset: "+00:00", subsec: nil]
  end
end
