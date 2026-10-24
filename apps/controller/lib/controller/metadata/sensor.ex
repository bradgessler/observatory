defmodule Controller.Metadata.Sensor do
  @moduledoc """
  What each camera's sensor is, by model: the numbers a frame's record needs
  for `XPIXSZ` and `BAYERPAT` and that a stack needs to carry a JPEG's plate
  solve onto RAW planes. One place for them instead of a constant in each
  module (`docs/metadata.md`, gap 9). Only what is known for certain is
  here; a model that isn't listed has no profile and its records say
  nothing about the sensor.

      Sensor.profile("ILCE-6000")
      #=> %{model: "ILCE-6000", w_px: 6000, h_px: 4000, raw_w_px: 6024, raw_h_px: 4024,
      #     pixel_um: 3.92, w_mm: 23.5, h_mm: 15.6, cfa: "RGGB"}
  """

  @profiles %{
    # Sony a6000: APS-C, 24 MP; the JPEG's 6000 x 4000 sits inside the RAW's 6024 x 4024
    "ILCE-6000" => %{w_px: 6000, h_px: 4000, raw_w_px: 6024, raw_h_px: 4024, pixel_um: 3.92, w_mm: 23.5, h_mm: 15.6, cfa: "RGGB"},
    # SVBONY SV105C (Sony IMX307): read as luma, so no colour filter pattern in what is kept
    "IMX307" => %{w_px: 1920, h_px: 1080, pixel_um: 2.9, w_mm: 5.6, h_mm: 3.1}
  }

  @doc "The profile for a camera model (or a name that contains one), or nil."
  def profile(nil), do: nil

  def profile(model) do
    name = to_string(model)

    Enum.find_value(@profiles, fn {key, p} ->
      if String.contains?(String.upcase(name), key), do: Map.put(p, :model, key)
    end) || if(name =~ ~r/SV105|SVBONY/i, do: Map.put(@profiles["IMX307"], :model, "IMX307"))
  end
end
