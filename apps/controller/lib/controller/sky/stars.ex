defmodule Controller.Sky.Stars do
  @moduledoc """
  A pocket catalog: the brightest stars plus a handful of crowd-pleasers, J2000,
  hand-entered to about an arcminute. Enough for a first sky map and for
  pointing a scope before plate solving takes over. A real catalog import is #4.
  """

  # {name, ra_hours, dec_degrees, magnitude, kind}
  @objects [
    {"Sirius", 6.7525, -16.7161, -1.46, :star},
    {"Canopus", 6.3992, -52.6957, -0.74, :star},
    {"Arcturus", 14.2610, 19.1824, -0.05, :star},
    {"Vega", 18.6156, 38.7837, 0.03, :star},
    {"Capella", 5.2782, 45.9980, 0.08, :star},
    {"Rigel", 5.2423, -8.2016, 0.13, :star},
    {"Procyon", 7.6550, 5.2250, 0.34, :star},
    {"Betelgeuse", 5.9195, 7.4071, 0.42, :star},
    {"Achernar", 1.6286, -57.2368, 0.46, :star},
    {"Altair", 19.8464, 8.8683, 0.76, :star},
    {"Aldebaran", 4.5987, 16.5093, 0.86, :star},
    {"Antares", 16.4901, -26.4320, 0.96, :star},
    {"Spica", 13.4199, -11.1613, 0.97, :star},
    {"Pollux", 7.7553, 28.0262, 1.14, :star},
    {"Fomalhaut", 22.9608, -29.6222, 1.16, :star},
    {"Deneb", 20.6905, 45.2803, 1.25, :star},
    {"Regulus", 10.1395, 11.9672, 1.35, :star},
    {"Castor", 7.5767, 31.8883, 1.58, :star},
    {"Bellatrix", 5.4189, 6.3497, 1.64, :star},
    {"Elnath", 5.4382, 28.6075, 1.65, :star},
    {"Alnilam", 5.6036, -1.2019, 1.69, :star},
    {"Alnitak", 5.6793, -1.9426, 1.74, :star},
    {"Alioth", 12.9005, 55.9598, 1.76, :star},
    {"Dubhe", 11.0621, 61.7510, 1.79, :star},
    {"Mirfak", 3.4054, 49.8612, 1.79, :star},
    {"Alkaid", 13.7923, 49.3133, 1.85, :star},
    {"Kaus Australis", 18.4029, -34.3846, 1.85, :star},
    {"Alhena", 6.6285, 16.3993, 1.93, :star},
    {"Mintaka", 5.5334, -0.2991, 2.23, :star},
    {"Polaris", 2.5303, 89.2641, 1.98, :star},
    {"Alpheratz", 0.1398, 29.0904, 2.06, :star},
    {"Mizar", 13.3988, 54.9254, 2.04, :star},
    {"Rasalhague", 17.5822, 12.5600, 2.08, :star},
    {"Kochab", 14.8451, 74.1555, 2.07, :star},
    {"Denebola", 11.8177, 14.5720, 2.14, :star},
    {"Algol", 3.1361, 40.9556, 2.12, :star},
    {"Almach", 2.0650, 42.3297, 2.10, :star},
    {"Hamal", 2.1196, 23.4624, 2.01, :star},
    {"Menkalinan", 5.9921, 44.9474, 1.90, :star},
    {"Alderamin", 21.3097, 62.5856, 2.45, :star},
    {"Eltanin", 17.9434, 51.4889, 2.24, :star},
    {"Sadr", 20.3705, 40.2567, 2.23, :star},
    {"Albireo", 19.5120, 27.9597, 3.05, :star},
    {"Enif", 21.7364, 9.8750, 2.38, :star},
    {"Scheat", 23.0629, 28.0828, 2.44, :star},
    {"Markab", 23.0793, 15.2053, 2.49, :star},
    {"Caph", 0.1529, 59.1498, 2.28, :star},
    {"Schedar", 0.6751, 56.5373, 2.24, :star},
    {"M31 Andromeda", 0.7123, 41.2692, 3.4, :galaxy},
    {"M42 Orion Nebula", 5.5881, -5.3911, 4.0, :nebula},
    {"M45 Pleiades", 3.7833, 24.1167, 1.6, :cluster},
    {"M13 Hercules Cluster", 16.6949, 36.4613, 5.8, :cluster},
    {"M57 Ring Nebula", 18.8931, 33.0292, 8.8, :nebula},
    {"M27 Dumbbell", 19.9934, 22.7212, 7.5, :nebula},
    {"M44 Beehive", 8.6733, 19.9833, 3.7, :cluster},
    {"Double Cluster", 2.3333, 57.1333, 4.3, :cluster},
    {"M81 Bode's Galaxy", 9.9259, 69.0653, 6.9, :galaxy},
    {"M51 Whirlpool", 13.4979, 47.1952, 8.4, :galaxy}
  ]

  def all do
    Enum.map(@objects, fn {name, ra_h, dec, mag, kind} ->
      %{id: slug(name), name: name, ra_deg: ra_h * 15, dec_deg: dec, mag: mag, kind: kind}
    end)
  end

  def get(id), do: Enum.find(all(), &(&1.id == id))

  defp slug(name), do: name |> String.downcase() |> String.replace(~r/[^a-z0-9]+/, "-")
end
