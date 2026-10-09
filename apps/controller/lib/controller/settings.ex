defmodule Controller.Settings do
  @moduledoc """
  Small persisted settings for this machine: the local horizon (tree line)
  per compass sector, the site, the camera's knobs, and whatever else the UI
  needs to remember between nights. Every value is plain JSON (maps with
  string keys, lists, strings, numbers, booleans), and a change on one
  phone is broadcast so every page shows it.

  **Where they live.** In the database (`Controller.Repo`, a row per key),
  so a change writes one row, not the whole file. The first time the
  database is up, `~/.observatory/settings.json` (`/data/observatory/` on a
  box) is brought in and kept beside as `settings.json.imported`. When the
  database isn't up (it failed to open or migrate), settings carry on from
  and to the JSON file as before: the scope never stops over its settings.

  Reads come from memory; writes go to memory, then to disk.
  """
  use Agent
  require Logger

  import Ecto.Query
  alias Controller.Repo
  alias Controller.Sky.Astro

  @sectors ~w(N NE E SE S SW W NW)
  @default_horizon Map.new(@sectors, &{&1, 20})

  def start_link(_), do: Agent.start_link(fn -> read() end, name: __MODULE__)

  def get(key, default \\ nil), do: Agent.get(__MODULE__, &Map.get(&1, key, default))

  @topic "settings"

  @doc "Every page subscribes: a change made on one phone shows on all of them."
  def subscribe, do: Telescope.subscribe(@topic)

  def put(key, value) do
    Agent.update(__MODULE__, fn s ->
      s = Map.put(s, key, value)
      write(s, key, value)
      s
    end)

    Telescope.broadcast(@topic, {:settings, key, value})
    :ok
  end

  @doc "Minimum visible altitude per compass sector, degrees."
  # an empty tree line (put back to nil) is no tree line: the default stands in
  def horizon, do: (get("horizon") || @default_horizon) |> Map.merge(%{}, fn _, a, _ -> a end)

  def sectors, do: @sectors

  @doc "Tree-line altitude in the direction of azimuth `az` (degrees)."
  def horizon_at(horizon, az) do
    i = round(Astro.norm360(az) / 45) |> rem(8)
    Map.get(horizon, Enum.at(@sectors, i), 20)
  end

  @doc "Where settings are kept right now: `:database`, or `:json` when the database isn't up."
  def store, do: if(Repo.up?(), do: :database, else: :json)

  # -- reading and writing --------------------------------------------------------------------

  # tests point this at a scratch file so they never read or write the real one
  defp path, do: Application.get_env(:controller, :settings_path) || Path.join([System.user_home!(), ".observatory", "settings.json"])

  @doc false
  # what start_link loads: public for the tests
  def load, do: read()

  defp read do
    if Repo.up?() do
      db = db_read()

      # a settings.json still here (the first boot with a database, or written while it was down):
      # what the database doesn't have comes in, then the file is kept beside
      case File.read(path()) do
        {:ok, bin} ->
          json = with {:ok, m} <- Jason.decode(bin), do: m, else: (_ -> %{})
          import_json(Map.drop(json, Map.keys(db)))
          Map.merge(json, db)

        _ ->
          db
      end
    else
      read_json()
    end
  rescue
    e ->
      Logger.error("settings: database read failed (#{Exception.message(e)}); using settings.json")
      read_json()
  end

  defp db_read do
    from(s in "settings", select: {s.key, s.value})
    |> Repo.all()
    |> Map.new(fn {k, v} -> {k, Jason.decode!(v)} end)
  end

  defp import_json(json) when map_size(json) == 0, do: File.rename(path(), path() <> ".imported")

  defp import_json(json) do
    now = DateTime.utc_now()
    rows = for {k, v} <- json, do: %{key: k, value: Jason.encode!(v), inserted_at: now, updated_at: now}
    Repo.insert_all("settings", rows, on_conflict: :nothing)
    File.rename(path(), path() <> ".imported")
    Logger.info("settings: #{length(rows)} brought into the database from #{path()}")
  end

  defp write(map, key, value) do
    if Repo.up?() do
      now = DateTime.utc_now()

      Repo.insert_all("settings", [%{key: key, value: Jason.encode!(value), inserted_at: now, updated_at: now}],
        on_conflict: {:replace, [:value, :updated_at]},
        conflict_target: [:key]
      )
    else
      write_json(map)
    end
  rescue
    e ->
      Logger.error("settings: database write failed (#{Exception.message(e)}); writing settings.json")
      write_json(map)
  end

  # the file, or the copy kept when it was brought into the database (stale, but better than nothing)
  defp read_json do
    Enum.find_value([path(), path() <> ".imported"], %{}, fn p ->
      with {:ok, bin} <- File.read(p), {:ok, map} <- Jason.decode(bin), do: map, else: (_ -> nil)
    end)
  end

  defp write_json(map) do
    File.mkdir_p!(Path.dirname(path()))
    File.write!(path(), Jason.encode!(map, pretty: true))
  end
end
