defmodule Camera.Raw do
  @moduledoc """
  The preview JPEG a camera keeps inside its RAW file, for measuring and showing a picture taken RAW only.

  18 October 2026, Brad: "why fuck with jpg? Just do raw." The box needs a picture it can read quickly for every
  frame (star size, plate solving, cloud, the sensor's dust, the page), and a Sony ARW carries one: the a6000's is
  1616 x 1080, about 240 kB, the camera's own rendering of the exposure. It is found through the file's TIFF
  structure (JPEGInterchangeFormat, tag 0x201, and its length, 0x202, in IFD0, the IFD chain and SubIFDs), never by
  searching the bytes, and the largest one wins (the chain also holds a 160 x 120 thumbnail). Nothing is decoded or
  changed: the bytes are the camera's.
  """

  @doc "The largest embedded JPEG in a TIFF-based RAW (ARW, DNG, NEF, CR2...), or nil."
  def preview(<<"II", 42::16-little, ifd0::32-little, _::binary>> = raw), do: best(raw, :little, ifd0)
  def preview(<<"MM", 42::16-big, ifd0::32-big, _::binary>> = raw), do: best(raw, :big, ifd0)
  def preview(_), do: nil

  defp best(raw, endian, ifd0) do
    raw
    |> jpegs(endian, [ifd0], MapSet.new(), [])
    |> Enum.filter(&match?(<<0xFF, 0xD8, _::binary>>, &1))
    |> Enum.max_by(&byte_size/1, fn -> nil end)
  end

  defp jpegs(_raw, _e, [], _seen, acc), do: acc

  defp jpegs(raw, e, [off | rest], seen, acc) do
    if off <= 0 or off + 2 > byte_size(raw) or MapSet.member?(seen, off) do
      jpegs(raw, e, rest, seen, acc)
    else
      {tags, next} = ifd(raw, e, off)
      acc = if tags[0x201] && tags[0x202], do: [slice(raw, tags[0x201], tags[0x202]) | acc], else: acc
      subs = sub_ifds(raw, e, tags[0x14A])
      jpegs(raw, e, [next | subs] ++ rest, MapSet.put(seen, off), acc)
    end
  end

  # an IFD: its entries as %{tag => value or {count, offset}}, and the next IFD's offset
  defp ifd(raw, e, off) do
    n = u16(raw, e, off)

    tags =
      for i <- 0..(n - 1)//1, into: %{} do
        p = off + 2 + 12 * i
        tag = u16(raw, e, p)
        type = u16(raw, e, p + 2)
        count = u32(raw, e, p + 4)
        value = if type == 3 and count == 1, do: u16(raw, e, p + 8), else: u32(raw, e, p + 8)
        {tag, if(count == 1, do: value, else: {count, value})}
      end

    {tags, u32(raw, e, off + 2 + 12 * n)}
  rescue
    _ -> {%{}, 0}
  end

  defp sub_ifds(_raw, _e, nil), do: []
  defp sub_ifds(_raw, _e, off) when is_integer(off), do: [off]
  defp sub_ifds(raw, e, {count, off}), do: for(i <- 0..(count - 1)//1, do: u32(raw, e, off + 4 * i))

  defp slice(raw, off, len) when is_integer(off) and is_integer(len) and off >= 0 and len > 0 and off + len <= byte_size(raw),
    do: binary_part(raw, off, len)

  defp slice(_, _, _), do: nil

  defp u16(raw, :little, p), do: (<<v::16-little>> = binary_part(raw, p, 2); v)
  defp u16(raw, :big, p), do: (<<v::16-big>> = binary_part(raw, p, 2); v)
  defp u32(raw, :little, p), do: (<<v::32-little>> = binary_part(raw, p, 4); v)
  defp u32(raw, :big, p), do: (<<v::32-big>> = binary_part(raw, p, 4); v)

  @doc """
  A minimal little-endian TIFF holding `jpeg` as its preview: for the simulated camera and tests, so a RAW-only
  picture goes through the same path as a real one.
  """
  def wrap(jpeg, padding \\ "simulated raw data") when is_binary(jpeg) do
    entries = 2
    ifd_size = 2 + 12 * entries + 4
    jpeg_off = 8 + ifd_size + byte_size(padding)

    ifd =
      <<entries::16-little, 0x201::16-little, 4::16-little, 1::32-little, jpeg_off::32-little, 0x202::16-little, 4::16-little, 1::32-little,
        byte_size(jpeg)::32-little, 0::32-little>>

    <<"II", 42::16-little, 8::32-little>> <> ifd <> padding <> jpeg
  end
end
