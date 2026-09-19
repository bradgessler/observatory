defmodule Controller.Sky.Catalog do
  @moduledoc """
  Stars to mag 6, the Messier list plus named bright DSOs, and constellation
  lines — from the d3-celestial data set (`priv/sky/*.json`, BSD licensed,
  https://github.com/ofrohn/d3-celestial). Parsed once at boot into
  `:persistent_term`; everything is a plain list of maps.

  Coordinates are J2000. RA is stored in degrees 0–360.
  """
  use GenServer
  require Logger

  @dir :code.priv_dir(:controller) |> Path.join("sky")

  def start_link(_), do: GenServer.start_link(__MODULE__, [], name: __MODULE__)

  @impl true
  def init(_) do
    load()
    {:ok, %{}}
  end

  @doc "Stars at or brighter than `mag_limit`."
  def stars(mag_limit \\ 5.0), do: Enum.filter(get(:stars), &(&1.mag <= mag_limit))

  @doc "Named star lookup by id."
  def star(id), do: Enum.find(get(:stars), &(&1.id == id))

  def dsos, do: get(:dsos)
  def dso(id), do: Enum.find(get(:dsos), &(&1.id == id))

  @doc "Constellation line segments as lists of `{ra_deg, dec_deg}`."
  def lines, do: get(:lines)

  def object(id), do: star(id) || dso(id)

  defp get(key), do: :persistent_term.get({__MODULE__, key}, [])

  # -- loading -----------------------------------------------------------------------

  def load do
    stars = load_stars()
    dsos = load_dsos()
    lines = load_lines()
    :persistent_term.put({__MODULE__, :stars}, stars)
    :persistent_term.put({__MODULE__, :dsos}, dsos)
    :persistent_term.put({__MODULE__, :lines}, lines)
    Logger.info("sky catalog: #{length(stars)} stars, #{length(dsos)} DSOs, #{length(lines)} constellation lines")
  end

  defp load_stars do
    names = read("starnames.json") || %{}

    for f <- features("stars.6.json") do
      hip = f["id"]
      [ra, dec] = f["geometry"]["coordinates"]
      n = names[to_string(hip)] || %{}
      proper = blank_to_nil(n["name"])
      bayer = blank_to_nil(n["bayer"])
      con = blank_to_nil(n["c"])

      %{
        id: "hip#{hip}",
        name: proper || (bayer && con && "#{bayer} #{con}") || "HIP #{hip}",
        proper: proper,
        ra_deg: ra360(ra),
        dec_deg: dec,
        mag: num(f["properties"]["mag"]),
        kind: :star
      }
    end
    |> Enum.sort_by(& &1.mag)
  end

  defp load_dsos do
    names = read("dsonames.json") || %{}

    messier =
      for f <- features("messier.json") do
        p = f["properties"]
        [ra, dec] = f["geometry"]["coordinates"]
        alt = blank_to_nil(p["alt"])

        %{
          id: String.downcase(f["id"]),
          name: if(alt, do: "#{f["id"]} #{alt}", else: "#{f["id"]} #{p["desig"]}"),
          ra_deg: ra360(ra),
          dec_deg: dec,
          mag: num(p["mag"]),
          kind: dso_kind(p["type"])
        }
      end

    # Same object under two catalog numbers (M13 / NGC 6205): dedupe by sky position.
    messier_cells = MapSet.new(messier, &cell(&1.ra_deg, &1.dec_deg))

    # Named non-Messier showpieces from the bright list (skip dark nebulae / unknown mags).
    extras =
      for f <- features("dsos.6.json"),
          p = f["properties"],
          mag = num(p["mag"]),
          mag < 9.0,
          # visual objects only: skip dark nebulae, sprawling star-forming regions, positions
          p["type"] in ["oc", "gc", "pn", "g", "s", "s0", "sd", "e", "i", "bn", "rn", "snr", "gg"],
          not big?(p["dim"]),
          n = names[to_string(f["id"])],
          is_binary(n["name"]) and n["name"] != "",
          [ra, dec] = f["geometry"]["coordinates"],
          not MapSet.member?(messier_cells, cell(ra360(ra), dec)) do
        id = f["id"] |> String.downcase() |> String.replace(~r/\s+/, "")
        %{id: id, name: n["name"], desig: f["id"], ra_deg: ra360(ra), dec_deg: dec, mag: mag, kind: dso_kind(p["type"])}
      end

    Enum.sort_by(messier ++ extras, & &1.mag)
  end

  defp load_lines do
    for f <- features("constellations.lines.json"),
        line <- f["geometry"]["coordinates"] do
      Enum.map(line, fn [ra, dec] -> {ra360(ra), dec} end)
    end
  end

  defp features(file) do
    case read(file) do
      %{"features" => fs} -> fs
      _ -> []
    end
  end

  defp read(file) do
    path = Path.join(@dir, file)

    with true <- File.exists?(path),
         {:ok, bin} <- File.read(path),
         {:ok, json} <- Jason.decode(bin) do
      json
    else
      _ ->
        Logger.warning("sky catalog: #{file} missing or unreadable")
        nil
    end
  end

  # ~0.2° grid cell for "same object" checks.
  defp cell(ra, dec), do: {round(ra * 5), round(dec * 5)}

  # Anything over ~2° across is a binocular/naked-eye object, not an eyepiece target.
  defp big?(dim) when is_binary(dim) do
    case Integer.parse(dim) do
      {n, _} -> n > 120
      :error -> false
    end
  end

  defp big?(_), do: false

  defp ra360(ra) when ra < 0, do: ra + 360.0
  defp ra360(ra), do: ra * 1.0

  defp num(n) when is_number(n), do: n * 1.0
  defp num(s) when is_binary(s), do: (case Float.parse(s), do: ({f, _} -> f; :error -> 99.0))
  defp num(_), do: 99.0

  defp blank_to_nil(""), do: nil
  defp blank_to_nil(v), do: v

  defp dso_kind("g"), do: :galaxy
  defp dso_kind(t) when t in ["s", "s0", "sd", "e", "i", "gg"], do: :galaxy
  defp dso_kind("oc"), do: :cluster
  defp dso_kind("gc"), do: :cluster
  defp dso_kind("pn"), do: :nebula
  defp dso_kind(t) when t in ["bn", "en", "rn", "sfr", "snr", "n"], do: :nebula
  defp dso_kind(_), do: :nebula
end
