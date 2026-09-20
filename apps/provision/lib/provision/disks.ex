defmodule Provision.Disks do
  @moduledoc """
  The removable disks attached to this machine, and nothing else.

  Writing an image destroys whatever was on the disk, so this list is the
  first safety rail: it only ever reports disks the operating system calls
  external and removable. The internal drive cannot appear here, which means
  the page cannot offer it and a mistaken tap cannot take the machine out.
  """

  @doc """
  Attached removable disks, newest first, as

      %{id: "/dev/disk4", name: "SanDisk Extreme SSD", size_bytes: 1_000_204_886_016,
        size: "1.0 TB", removable: true, mounted: ["/Volumes/UNTITLED"]}
  """
  def list do
    case :os.type() do
      {:unix, :darwin} -> mac()
      {:unix, _} -> linux()
      _ -> []
    end
  rescue
    _ -> []
  end

  # -- macOS ----------------------------------------------------------------------------

  defp mac do
    with {out, 0} <- System.cmd("diskutil", ["list", "-plist", "external", "physical"]),
         ids when ids != [] <- Regex.scan(~r|<string>(disk\d+)</string>|, out) |> Enum.map(&List.last/1) |> Enum.uniq() do
      ids |> Enum.map(&mac_info/1) |> Enum.reject(&is_nil/1)
    else
      _ -> []
    end
  end

  defp mac_info(id) do
    case System.cmd("diskutil", ["info", "-plist", id]) do
      {out, 0} ->
        removable? = plist_bool(out, "Removable") or plist_bool(out, "RemovableMediaOrExternalDevice") or plist_bool(out, "Ejectable")
        size = plist_int(out, "TotalSize") || plist_int(out, "Size") || 0

        if removable? and size > 0 do
          %{
            id: "/dev/" <> id,
            raw_id: "/dev/r" <> id,
            name: plist_str(out, "MediaName") || plist_str(out, "IORegistryEntryName") || id,
            size_bytes: size,
            size: human(size),
            removable: true,
            mounted: mac_mounts(id)
          }
        end

      _ ->
        nil
    end
  end

  defp mac_mounts(id) do
    case System.cmd("diskutil", ["list", "-plist", "/dev/" <> id]) do
      {out, 0} -> Regex.scan(~r|<key>MountPoint</key>\s*<string>([^<]+)</string>|, out) |> Enum.map(&List.last/1)
      _ -> []
    end
  end

  # The plists are small and ours; a regex beats pulling in an XML parser.
  defp plist_str(xml, key) do
    case Regex.run(~r|<key>#{key}</key>\s*<string>([^<]*)</string>|, xml) do
      [_, v] -> v
      _ -> nil
    end
  end

  defp plist_int(xml, key) do
    case Regex.run(~r|<key>#{key}</key>\s*<integer>(\d+)</integer>|, xml) do
      [_, v] -> String.to_integer(v)
      _ -> nil
    end
  end

  defp plist_bool(xml, key), do: Regex.match?(~r|<key>#{key}</key>\s*<true/>|, xml)

  # -- Linux ----------------------------------------------------------------------------

  defp linux do
    case System.cmd("lsblk", ["-J", "-b", "-o", "NAME,MODEL,SIZE,RM,TYPE,MOUNTPOINT"]) do
      {out, 0} ->
        out
        |> parse_lsblk()
        |> Enum.filter(&(&1.removable and &1.size_bytes > 0))

      _ ->
        []
    end
  end

  defp parse_lsblk(json) do
    # a tiny reader for the shape lsblk emits; no JSON dependency in this app
    Regex.scan(~r/\{"name":"([^"]+)","model":([^,]+),"size":(\d+),"rm":(true|false),"type":"([^"]+)"/, json)
    |> Enum.filter(fn [_, _, _, _, _, type] -> type == "disk" end)
    |> Enum.map(fn [_, name, model, size, rm, _] ->
      %{
        id: "/dev/" <> name,
        raw_id: "/dev/" <> name,
        name: model |> String.trim(~s(")) |> String.trim() |> then(&if(&1 in ["null", ""], do: name, else: &1)),
        size_bytes: String.to_integer(size),
        size: human(String.to_integer(size)),
        removable: rm == "true",
        mounted: []
      }
    end)
  end

  @doc "Bytes as a person reads them."
  def human(b) when b >= 1_000_000_000_000, do: "#{Float.round(b / 1_000_000_000_000, 1)} TB"
  def human(b) when b >= 1_000_000_000, do: "#{Float.round(b / 1_000_000_000, 1)} GB"
  def human(b) when b >= 1_000_000, do: "#{Float.round(b / 1_000_000, 0)} MB"
  def human(b), do: "#{b} B"

  @doc """
  Is this disk still one of the removable disks we can see? Checked again
  immediately before writing, so a card swapped between choosing and pressing
  cannot be written by mistake.
  """
  def still_there?(id), do: Enum.any?(list(), &(&1.id == id))
end
