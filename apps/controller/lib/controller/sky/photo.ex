defmodule Controller.Sky.Photo do
  @moduledoc """
  The little a plate solve needs to know about a photo before it runs: what
  format it is, how big, and when it was taken. Read straight from the bytes
  (JPEG markers and EXIF, the PNG header, a netpbm or FITS header), no image
  library.

      Photo.format(bytes)      # :jpeg | :png | :pgm | :ppm | :fits | :heic | :unknown
      Photo.dimensions(bytes)  # {:ok, {width, height}} | :error
      Photo.taken_at(bytes)    # %DateTime{} (UTC) | nil

  `taken_at/1` is EXIF DateTimeOriginal with OffsetTimeOriginal (and
  SubSecTimeOriginal when present). Without the offset the local time is
  ambiguous, so it says nil rather than guess; the caller falls back to the
  upload time. An iPhone writes both.
  """

  @doc "The image format, from its first bytes."
  def format(<<0xFF, 0xD8, 0xFF, _::binary>>), do: :jpeg
  def format(<<0x89, "PNG", 0x0D, 0x0A, 0x1A, 0x0A, _::binary>>), do: :png
  def format(<<"P5", c, _::binary>>) when c in ~c" \t\r\n", do: :pgm
  def format(<<"P6", c, _::binary>>) when c in ~c" \t\r\n", do: :ppm
  def format(<<"SIMPLE  =", _::binary>>), do: :fits

  def format(<<_::binary-4, "ftyp", brand::binary-4, _::binary>>)
      when brand in ["heic", "heix", "mif1", "msf1", "hevc", "heim", "heis"], do: :heic

  def format(_), do: :unknown

  @doc "The file extension solve-field wants for a format (it sniffs, but the name should not lie)."
  def extension(:jpeg), do: ".jpg"
  def extension(:png), do: ".png"
  def extension(:pgm), do: ".pgm"
  def extension(:ppm), do: ".ppm"
  def extension(:fits), do: ".fits"
  def extension(_), do: ".img"

  @doc "Pixel width and height."
  def dimensions(bytes) do
    case format(bytes) do
      :jpeg -> jpeg_dims(bytes, 2)
      :png -> png_dims(bytes)
      f when f in [:pgm, :ppm] -> pnm_dims(bytes)
      :fits -> fits_dims(bytes)
      _ -> :error
    end
  end

  defp png_dims(<<_::binary-16, w::32, h::32, _::binary>>), do: {:ok, {w, h}}
  defp png_dims(_), do: :error

  # NAXIS1 and NAXIS2 among the 80-column cards of the first header block
  defp fits_dims(bytes) do
    cards =
      for <<card::binary-80 <- binary_part(bytes, 0, min(byte_size(bytes), 2880))>>, do: card

    value = fn key ->
      Enum.find_value(cards, fn card ->
        with true <- String.starts_with?(card, key),
             [_, v] <- Regex.run(~r/^\s*=\s*(\d+)/, binary_part(card, 8, 72)),
             do: String.to_integer(v),
             else: (_ -> nil)
      end)
    end

    case {value.("NAXIS1  "), value.("NAXIS2  ")} do
      {w, h} when is_integer(w) and is_integer(h) -> {:ok, {w, h}}
      _ -> :error
    end
  end

  # "P5 <w> <h> <max>" with whitespace and # comments between the tokens
  defp pnm_dims(<<_::binary-2, rest::binary>>) do
    tokens =
      rest
      |> binary_part(0, min(byte_size(rest), 512))
      |> String.split("\n")
      |> Enum.map(&(&1 |> String.split("#") |> hd()))
      |> Enum.join(" ")
      |> String.split(~r/\s+/, trim: true)

    with [w, h | _] <- tokens, {w, ""} <- Integer.parse(w), {h, ""} <- Integer.parse(h) do
      {:ok, {w, h}}
    else
      _ -> :error
    end
  end

  # Walk the JPEG markers to the first start-of-frame; its header carries the size.
  @sof [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF]

  defp jpeg_dims(bytes, at) when at + 4 <= byte_size(bytes) do
    case bytes do
      <<_::binary-size(^at), 0xFF, 0xFF, _::binary>> ->
        jpeg_dims(bytes, at + 1)

      <<_::binary-size(^at), 0xFF, m, _len::16, _p, h::16, w::16, _::binary>> when m in @sof ->
        {:ok, {w, h}}

      <<_::binary-size(^at), 0xFF, m, len::16, _::binary>> when m not in [0xD8, 0xD9, 0xDA] ->
        jpeg_dims(bytes, at + 2 + len)

      _ ->
        :error
    end
  end

  defp jpeg_dims(_, _), do: :error

  # -- when -------------------------------------------------------------------------

  @doc "When the photo was taken, in UTC, from EXIF; nil when it cannot be known."
  def taken_at(bytes) do
    with :jpeg <- format(bytes),
         {:ok, tags} <- exif(bytes),
         %{0x9003 => original, 0x9011 => offset} <- tags,
         {:ok, naive} <- exif_naive(original, tags[0x9291]),
         {:ok, seconds} <- offset_seconds(offset) do
      naive |> DateTime.from_naive!("Etc/UTC") |> DateTime.add(-seconds, :second)
    else
      _ -> nil
    end
  end

  @doc """
  The Exif IFD's text tags that matter here, as `%{tag => string}`:
  DateTimeOriginal (0x9003), OffsetTimeOriginal (0x9011),
  SubSecTimeOriginal (0x9291).
  """
  def exif(bytes) do
    with {:ok, tiff} <- app1_tiff(bytes, 2),
         {:ok, endian, ifd0} <- tiff_header(tiff),
         {:ok, entries0} <- ifd(tiff, endian, ifd0),
         {:ok, exif_at} <- pointer(entries0, 0x8769, endian),
         {:ok, entries} <- ifd(tiff, endian, exif_at) do
      {:ok,
       for {tag, 2, count, raw} <- entries, tag in [0x9003, 0x9011, 0x9291], into: %{} do
         {tag, ascii(tiff, endian, count, raw)}
       end}
    else
      _ -> :error
    end
  end

  # APP1 segments until one that starts "Exif\0\0"; the TIFF block follows it
  defp app1_tiff(bytes, at) when at + 4 <= byte_size(bytes) do
    case bytes do
      <<_::binary-size(^at), 0xFF, 0xE1, len::16, "Exif", 0, 0, _::binary>>
      when at + 2 + len <= byte_size(bytes) ->
        {:ok, binary_part(bytes, at + 10, len - 8)}

      <<_::binary-size(^at), 0xFF, m, len::16, _::binary>>
      when m not in [0xD8, 0xD9, 0xDA] and m >= 0xC0 ->
        app1_tiff(bytes, at + 2 + len)

      _ ->
        :error
    end
  end

  defp app1_tiff(_, _), do: :error

  defp tiff_header(<<"II", 42::little-16, off::little-32, _::binary>>), do: {:ok, :little, off}
  defp tiff_header(<<"MM", 42::big-16, off::big-32, _::binary>>), do: {:ok, :big, off}
  defp tiff_header(_), do: :error

  defp ifd(tiff, endian, at) when at + 2 <= byte_size(tiff) do
    n = uint(binary_part(tiff, at, 2), endian)

    if at + 2 + n * 12 <= byte_size(tiff) do
      {:ok,
       for i <- 0..(n - 1)//1 do
         <<tag::binary-2, type::binary-2, count::binary-4, raw::binary-4>> =
           binary_part(tiff, at + 2 + i * 12, 12)

         {uint(tag, endian), uint(type, endian), uint(count, endian), raw}
       end}
    else
      :error
    end
  end

  defp ifd(_, _, _), do: :error

  defp pointer(entries, tag, endian) do
    case List.keyfind(entries, tag, 0) do
      {^tag, _type, _count, raw} -> {:ok, uint(raw, endian)}
      nil -> :error
    end
  end

  # ASCII of up to 4 bytes lives in the entry itself, longer at an offset
  defp ascii(_tiff, _endian, count, raw) when count <= 4,
    do: raw |> binary_part(0, count) |> cstring()

  defp ascii(tiff, endian, count, raw) do
    off = uint(raw, endian)
    if off + count <= byte_size(tiff), do: tiff |> binary_part(off, count) |> cstring(), else: ""
  end

  defp cstring(bin), do: bin |> :binary.split(<<0>>) |> hd() |> String.trim()

  defp uint(bin, :little), do: :binary.decode_unsigned(bin, :little)
  defp uint(bin, :big), do: :binary.decode_unsigned(bin, :big)

  # "2026:09:25 21:14:03" (+ "123" sub-seconds)
  defp exif_naive(
         <<y::binary-4, ":", mo::binary-2, ":", d::binary-2, " ", h::binary-2, ":", mi::binary-2,
           ":", s::binary-2, _::binary>>,
         subsec
       ) do
    us =
      case subsec && Integer.parse(subsec) do
        {n, ""} -> div(n * 1_000_000, Integer.pow(10, String.length(subsec)))
        _ -> 0
      end

    with {y, ""} <- Integer.parse(y),
         {mo, ""} <- Integer.parse(mo),
         {d, ""} <- Integer.parse(d),
         {h, ""} <- Integer.parse(h),
         {mi, ""} <- Integer.parse(mi),
         {s, ""} <- Integer.parse(s) do
      NaiveDateTime.new(y, mo, d, h, mi, s, {us, 6})
    else
      _ -> :error
    end
  end

  defp exif_naive(_, _), do: :error

  # "+02:00" / "-07:00"
  defp offset_seconds(<<sign, h::binary-2, ":", m::binary-2, _::binary>>) when sign in [?+, ?-] do
    with {h, ""} <- Integer.parse(h), {m, ""} <- Integer.parse(m) do
      {:ok, if(sign == ?-, do: -1, else: 1) * (h * 3600 + m * 60)}
    else
      _ -> :error
    end
  end

  defp offset_seconds(_), do: :error
end
