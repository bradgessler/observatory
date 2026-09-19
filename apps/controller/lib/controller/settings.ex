defmodule Controller.Settings do
  @moduledoc """
  Small persisted settings for this machine (`~/.observatory/settings.json`):
  the local horizon (tree line) per compass sector, and whatever else the UI
  needs to remember between nights. Everything is a plain map.
  """
  use Agent

  alias Controller.Sky.Astro

  @sectors ~w(N NE E SE S SW W NW)
  @default_horizon Map.new(@sectors, &{&1, 20})

  def start_link(_), do: Agent.start_link(fn -> read() end, name: __MODULE__)

  def get(key, default \\ nil), do: Agent.get(__MODULE__, &Map.get(&1, key, default))

  def put(key, value) do
    Agent.update(__MODULE__, fn s ->
      s = Map.put(s, key, value)
      write(s)
      s
    end)
  end

  @doc "Minimum visible altitude per compass sector, degrees."
  def horizon, do: get("horizon", @default_horizon) |> Map.merge(%{}, fn _, a, _ -> a end)

  def sectors, do: @sectors

  @doc "Tree-line altitude in the direction of azimuth `az` (degrees)."
  def horizon_at(horizon, az) do
    i = round(Astro.norm360(az) / 45) |> rem(8)
    Map.get(horizon, Enum.at(@sectors, i), 20)
  end

  defp path, do: Path.join([System.user_home!(), ".observatory", "settings.json"])

  defp read do
    with {:ok, bin} <- File.read(path()), {:ok, map} <- Jason.decode(bin), do: map, else: (_ -> %{})
  end

  defp write(map) do
    File.mkdir_p!(Path.dirname(path()))
    File.write!(path(), Jason.encode!(map, pretty: true))
  end
end
