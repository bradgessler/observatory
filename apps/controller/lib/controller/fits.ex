defmodule Controller.Fits do
  @moduledoc """
  FITS, the file astronomy software reads (Siril, PixInsight, astrometry.net,
  DS9, Astropy): the picture and everything known about it in one file. The
  header is 80-character "cards" of `KEYWORD = value / comment`, in 2880-byte
  blocks, then the pixels.

      Fits.encode(%{w: 960, h: 540, px: px}, [{"EXPTIME", 1.0, "seconds"}, {"OBS CAMERA GAIN", 100}])
      {:ok, %{w: 960, h: 540, px: px, header: header}} = Fits.read(bin)
      Fits.update(path, [{"OBS MAC STARS", 12}])

  **Cards.** `{key, value}` or `{key, value, comment}`; a nil value is left
  out (unknown is not zero). Standard keywords (up to 8 characters, `A-Z
  0-9 - _`) use the fixed format every reader takes. Anything longer, with
  spaces (`"OBS MOUNT RA DEG"`), is written by the ESO HIERARCH convention
  (`HIERARCH OBS MOUNT RA DEG = 12.5`), which Astropy, Siril and PixInsight
  read. `{:comment, text}` and `{:history, text}` are free text. Values are
  strings, integers, floats, booleans and `DateTime`s (ISO 8601, UTC). A
  header is ASCII only: `×` becomes `x`, `°` becomes `deg`, and so on.

  **Pixels.** 8-bit gray (`BITPIX = 8`), stored top row first and said so
  (`ROWORDER = 'TOP-DOWN'`, as capture programs write it), so the picture
  in the file is the picture on the page.

  **Updating.** `update/2` adds or replaces cards in a file already on disk.
  When the header still fits its blocks it's rewritten in place; otherwise
  the file is rewritten (the pixels move down a block).
  """

  @block 2880

  # -- writing -----------------------------------------------------------------------------

  @doc "An 8-bit gray image as a FITS file, `cards` in its header after the required ones."
  def encode(%{w: w, h: h, px: px}, cards \\ []) do
    required = [
      {"SIMPLE", true, "conforms to FITS standard"},
      {"BITPIX", 8, "8-bit unsigned pixels"},
      {"NAXIS", 2, "a picture"},
      {"NAXIS1", w, "width, pixels"},
      {"NAXIS2", h, "height, pixels"}
    ]

    header(required ++ cards) <> pad(binary_part(px, 0, w * h), 0)
  end

  defp header(cards) do
    cards
    |> Enum.flat_map(&card/1)
    |> Kernel.++([pad80("END")])
    |> IO.iodata_to_binary()
    |> pad(?\s)
  end

  @doc false
  def card({:comment, text}), do: free("COMMENT ", text)
  def card({:history, text}), do: free("HISTORY ", text)
  def card({key, value}), do: card({key, value, nil})
  def card({_key, nil, _comment}), do: []

  def card({key, value, comment}) do
    key = key |> ascii() |> String.upcase()
    v = value(value)

    head =
      if standard?(key) do
        # strings start in column 11; numbers and logicals end in column 30
        String.pad_trailing(key, 8) <> "= " <> if(is_binary(value) or match?(%DateTime{}, value), do: v, else: String.pad_leading(v, 20))
      else
        "HIERARCH " <> key <> " = " <> v
      end

    line = if comment, do: head <> " / " <> ascii(comment), else: head
    [pad80(String.slice(line, 0, 80))]
  end

  defp standard?(key), do: String.length(key) <= 8 and key =~ ~r/\A[A-Z0-9_-]+\z/

  # free text, wrapped at words into cards of 72 characters
  defp free(prefix, text) do
    text
    |> ascii()
    |> String.split(" ", trim: true)
    |> Enum.reduce([], fn
      word, [line | rest] when byte_size(line) + 1 + byte_size(word) <= 72 -> [line <> " " <> word | rest]
      word, lines -> [String.slice(word, 0, 72) | lines]
    end)
    |> Enum.reverse()
    |> Enum.map(&pad80(prefix <> &1))
  end

  defp value(true), do: "T"
  defp value(false), do: "F"
  defp value(v) when is_integer(v), do: Integer.to_string(v)
  defp value(v) when is_float(v), do: v |> :erlang.float_to_binary([:short]) |> String.upcase()
  defp value(%DateTime{} = t), do: string(t |> DateTime.truncate(:millisecond) |> DateTime.to_naive() |> NaiveDateTime.to_iso8601())
  defp value(v) when is_atom(v), do: string(Atom.to_string(v))
  defp value(v) when is_binary(v), do: string(v)
  defp value(v), do: string(inspect(v))

  # 'text', quotes doubled, at least 8 characters inside, at most what fits a card
  defp string(s) do
    inner = s |> ascii() |> String.replace("'", "''") |> String.slice(0, 66) |> String.pad_trailing(8)
    "'" <> inner <> "'"
  end

  @swaps [{"×", "x"}, {"°", " deg"}, {"′", "'"}, {"″", "\""}, {"—", "-"}, {"–", "-"}, {"·", "-"}, {"µ", "u"}, {"…", "..."}]

  # a header is printable ASCII only
  defp ascii(s) do
    s = to_string(s)
    s = Enum.reduce(@swaps, s, fn {a, b}, acc -> String.replace(acc, a, b) end)
    for <<c::utf8 <- s>>, into: "", do: if(c >= 32 and c <= 126, do: <<c>>, else: "?")
  end

  defp pad80(s), do: String.pad_trailing(s, 80)

  defp pad(bin, fill) do
    case rem(byte_size(bin), @block) do
      0 -> bin
      r -> bin <> :binary.copy(<<fill>>, @block - r)
    end
  end

  # -- reading -----------------------------------------------------------------------------

  @doc "The header as `[{key, value}]` in order (comments as `{\"COMMENT\", text}`), and the byte length it takes."
  def header_of(bin) do
    with {:ok, lines, size} <- lines(bin, 0, []), do: {:ok, Enum.map(lines, &parse/1), size}
  end

  # the header's 80-character lines up to END, as written
  defp lines(bin, at, acc) when byte_size(bin) >= at + 80 do
    case binary_part(bin, at, 80) do
      "END" <> rest -> if String.trim(rest) == "", do: {:ok, Enum.reverse(acc), blocks(at + 80)}, else: lines(bin, at + 80, acc)
      line -> lines(bin, at + 80, [line | acc])
    end
  end

  defp lines(_bin, _at, _acc), do: {:error, :no_end}

  defp blocks(n), do: div(n + @block - 1, @block) * @block

  defp parse("HIERARCH " <> rest) do
    case String.split(rest, "=", parts: 2) do
      [k, v] -> {String.trim(k), parse_value(v)}
      [k] -> {String.trim(k), nil}
    end
  end

  defp parse(<<key::binary-size(8), "= ", v::binary>>), do: {String.trim(key), parse_value(v)}
  defp parse(<<key::binary-size(8), text::binary>>), do: {String.trim(key), String.trim_trailing(text)}

  defp parse_value(v) do
    v = String.trim_leading(v)

    case v do
      "'" <> rest ->
        rest |> take_string("") |> String.trim_trailing()

      _ ->
        token = v |> String.split("/", parts: 2) |> hd() |> String.trim()

        cond do
          token == "T" -> true
          token == "F" -> false
          token =~ ~r/\A[+-]?\d+\z/ -> String.to_integer(token)
          true -> with {f, ""} <- Float.parse(token), do: f, else: (_ -> token)
        end
    end
  end

  defp take_string("''" <> rest, acc), do: take_string(rest, acc <> "'")
  defp take_string("'" <> _, acc), do: acc
  defp take_string(<<c::utf8, rest::binary>>, acc), do: take_string(rest, acc <> <<c::utf8>>)
  defp take_string("", acc), do: acc

  @doc "Just the header of the FITS file at `path`, read from its first blocks (a 50 MB frame is never read whole for it)."
  def read_header(path) do
    with {:ok, fd} <- :file.open(path, [:read, :binary, :raw]) do
      try do
        with {:ok, head} <- :file.pread(fd, 0, 64 * @block), {:ok, header, _size} <- header_of(head), do: {:ok, header}
      after
        :file.close(fd)
      end
    end
  end

  @doc "A FITS file's picture and header: `{:ok, %{w, h, px, header}}` (8-bit, top row first)."
  def read(bin) do
    with {:ok, header, at} <- header_of(bin),
         h = Map.new(header),
         8 <- h["BITPIX"],
         w when is_integer(w) <- h["NAXIS1"],
         rows when is_integer(rows) <- h["NAXIS2"],
         true <- byte_size(bin) >= at + w * rows do
      px = binary_part(bin, at, w * rows)
      # a bottom-up file (the FITS default) is turned the right way up
      px = if h["ROWORDER"] == "TOP-DOWN", do: px, else: flip(px, w, rows)
      {:ok, %{w: w, h: rows, px: px, header: header}}
    else
      {:error, e} -> {:error, e}
      _ -> {:error, :not_an_8_bit_picture}
    end
  end

  defp flip(px, w, h), do: IO.iodata_to_binary(for y <- (h - 1)..0//-1, do: binary_part(px, y * w, w))

  @doc "Add or replace `cards` in the FITS file at `path` (by keyword), keeping the rest."
  def update(path, cards) do
    {:ok, fd} = :file.open(path, [:read, :write, :binary, :raw])

    try do
      {:ok, head} = :file.pread(fd, 0, 64 * @block)
      {:ok, old, size} = lines(head, 0, [])
      keys = MapSet.new(cards, fn c -> if is_atom(elem(c, 0)), do: nil, else: c |> elem(0) |> ascii() |> String.upcase() end)

      # every other line kept exactly as written (its comment too); the new cards after them
      kept = Enum.reject(old, fn line -> MapSet.member?(keys, line |> parse() |> elem(0)) end)
      new = IO.iodata_to_binary([kept, Enum.flat_map(cards, &card/1), pad80("END")]) |> pad(?\s)

      if byte_size(new) == size do
        :ok = :file.pwrite(fd, 0, new)
      else
        {:ok, %{size: total}} = File.stat(path)
        {:ok, data} = :file.pread(fd, size, total - size)
        :file.close(fd)
        File.write!(path <> ".tmp", [new, data])
        File.rename!(path <> ".tmp", path)
      end

      :ok
    after
      :file.close(fd)
    end
  end
end
