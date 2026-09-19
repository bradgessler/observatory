defmodule Video.Ladder do
  @moduledoc """
  The quality ladder. Names are the ones people say; sizes are what they
  mean here. Bitrates suit a static scene (a telescope, mostly not moving)
  on a home network.
  """

  @rungs [
    %{id: :"1k", label: "1K", size: {1280, 720}, kbps: 3_000},
    %{id: :"2k", label: "2K", size: {1920, 1080}, kbps: 6_000},
    %{id: :"4k", label: "4K", size: {3840, 2160}, kbps: 16_000}
  ]

  def rungs, do: @rungs
  def ids, do: Enum.map(@rungs, & &1.id)
  def get(id), do: Enum.find(@rungs, &(&1.id == id))

  def parse(id) when is_atom(id), do: get(id)
  def parse(id) when is_binary(id), do: Enum.find(@rungs, &(Atom.to_string(&1.id) == String.downcase(id)))

  @doc "Does a camera with these modes (`[{w, h}]` or `:unknown`) offer this rung?"
  def available?(_rung, :unknown), do: true
  def available?(%{size: size}, modes) when is_list(modes), do: size in modes

  def size_string({w, h}), do: "#{w}x#{h}"
end
