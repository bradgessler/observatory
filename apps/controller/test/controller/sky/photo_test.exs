defmodule Controller.Sky.PhotoTest do
  @moduledoc "What a photo says about itself, from its bytes: format, size, and when the shutter opened."
  use ExUnit.Case, async: true

  alias Controller.Sky.Photo

  import Controller.Test.Jpeg, only: [jpeg: 0, jpeg: 1]

  test "formats by their first bytes" do
    assert Photo.format(jpeg()) == :jpeg
    assert Photo.format(<<0x89, "PNG", 0x0D, 0x0A, 0x1A, 0x0A, 0, 0>>) == :png
    assert Photo.format("P5\n2 2\n255\n" <> <<0, 0, 0, 0>>) == :pgm
    assert Photo.format(<<0, 0, 0, 24, "ftypheic", 0, 0>>) == :heic
    assert Photo.format("/tmp/some/path.jpg") == :unknown
  end

  test "sizes from a JPEG frame header, a PNG header and a netpbm header" do
    assert Photo.dimensions(jpeg()) == {:ok, {4032, 3024}}
    png = <<0x89, "PNG", 0x0D, 0x0A, 0x1A, 0x0A, 13::32, "IHDR", 640::32, 480::32, 8, 0, 0, 0, 0>>
    assert Photo.dimensions(png) == {:ok, {640, 480}}
    assert Photo.dimensions("P5\n# made by hand\n800 600\n255\n" <> <<0>>) == {:ok, {800, 600}}
  end

  test "the shutter time is EXIF's local time and offset, in UTC, to the millisecond" do
    assert Photo.taken_at(jpeg()) == ~U[2026-09-26 04:14:03.123000Z]
    assert Photo.taken_at(jpeg(endian: :big, offset: "+02:00", subsec: nil)) == ~U[2026-09-25 19:14:03.000000Z]
  end

  test "no offset, no time: the local time alone is ambiguous" do
    assert Photo.taken_at(jpeg(offset: nil)) == nil
    assert Photo.taken_at("P5\n1 1\n255\n" <> <<0>>) == nil
    assert Photo.taken_at(<<0xFF, 0xD8, 0xFF, 0xD9>>) == nil
  end

  test "a FITS image's size is in its header cards" do
    card = fn k, v -> String.pad_trailing(String.pad_trailing(k, 8) <> "= " <> String.pad_leading(v, 20), 80) end
    header = card.("SIMPLE", "T") <> card.("BITPIX", "8") <> card.("NAXIS", "2") <> card.("NAXIS1", "1200") <> card.("NAXIS2", "900") <> String.pad_trailing("END", 80)
    fits = String.pad_trailing(header, 2880)
    assert Photo.format(fits) == :fits
    assert Photo.dimensions(fits) == {:ok, {1200, 900}}
  end
end
