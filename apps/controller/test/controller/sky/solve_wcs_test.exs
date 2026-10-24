defmodule Controller.Sky.SolveWcsTest do
  @moduledoc """
  A plate solve's WCS, kept: read from what solve-field writes, carried onto the camera's full
  picture, and checked against astrometry.net's own sums (`wcs-xy2rd`) and against a solve of the
  full picture itself. The numbers are a real solve of a still from 18 October 2026 (a field in
  Lyra), on the box's 1,500 x 1,000 grey copy of the 6,000 x 4,000 JPEG.
  """
  use ExUnit.Case, async: true

  alias Controller.Sky.Solve.Wcs

  @copy [
    {"WCSAXES", 2}, {"CTYPE1", "RA---TAN-SIP"}, {"CTYPE2", "DEC--TAN-SIP"}, {"EQUINOX", 2000.0}, {"LONPOLE", 180.0}, {"LATPOLE", 0.0},
    {"CRVAL1", 279.130669496}, {"CRVAL2", 38.6007299382}, {"CRPIX1", 224.958896637}, {"CRPIX2", 521.315330505},
    {"CUNIT1", "deg"}, {"CUNIT2", "deg"},
    {"CD1_1", 0.000177939491145}, {"CD1_2", -0.000392916473035}, {"CD2_1", 0.000392689939346}, {"CD2_2", 0.000177692801668},
    {"IMAGEW", 1500}, {"IMAGEH", 1000},
    {"A_ORDER", 2}, {"A_0_0", 0}, {"A_0_1", 0}, {"A_0_2", -7.56297138609e-08}, {"A_1_0", 0}, {"A_1_1", 2.25152276918e-07}, {"A_2_0", 3.40811218986e-07},
    {"B_ORDER", 2}, {"B_0_0", 0}, {"B_0_1", 0}, {"B_0_2", 1.45197279025e-07}, {"B_1_0", 0}, {"B_1_1", 9.95748791152e-08}, {"B_2_0", 6.33518849647e-07},
    {"AP_ORDER", 2}, {"AP_0_0", -1.78004051891e-05}, {"AP_0_1", -1.76327903322e-08}, {"AP_0_2", 7.56411006556e-08}, {"AP_1_0", -1.6988139284e-07},
    {"AP_1_1", -2.24988497846e-07}, {"AP_2_0", -3.40224530024e-07},
    {"BP_ORDER", 2}, {"BP_0_0", -2.12724961661e-05}, {"BP_0_1", -3.38028240487e-08}, {"BP_0_2", -1.45215010385e-07}, {"BP_1_0", -2.22008425531e-07},
    {"BP_1_1", -9.90350604635e-08}, {"BP_2_0", -6.32751104272e-07}
  ]

  defp arcsec({r1, d1}, {r2, d2}), do: Controller.Sky.Astro.separation_radec(r1, d1, r2, d2) * 3600

  @tag :tmp_dir
  test "the WCS file solve-field writes is read whole, with the astrometry.net that wrote it", %{tmp_dir: dir} do
    cards = [{"SIMPLE", true}, {"BITPIX", 8}, {"NAXIS", 0}] ++ @copy ++ [{:history, "Created by the Astrometry.net suite."}, {:history, "Git revision 0.97"}, {"DATE", "2026-10-23T19:32:40"}, {:comment, "Index(0): index-4207-11.fits"}]
    path = Path.join(dir, "solve.wcs")
    File.write!(path, IO.iodata_to_binary([Enum.flat_map(cards, &Controller.Fits.card/1), String.pad_trailing("END", 80)]))

    assert {:ok, %{wcs: wcs, software: "astrometry.net 0.97"}} = Wcs.read(path)
    keys = Enum.map(wcs, &elem(&1, 0))
    assert Enum.take(keys, 4) == ~w(WCSAXES CTYPE1 CTYPE2 EQUINOX)
    # the frame said, beside the equinox: astrometry.net's catalogues are ICRS
    assert Enum.at(keys, 4) == "RADESYS" and Map.new(wcs)["RADESYS"] == "ICRS"
    assert "BP_2_0" in keys and "IMAGEW" in keys
    refute "DATE" in keys or "SIMPLE" in keys or "COMMENT" in keys
  end

  test "a pixel's place on the sky is astrometry.net's own (wcs-xy2rd), SIP and all" do
    # wcs-xy2rd -w solve.wcs -x X -y Y, astrometry.net 0.97
    for {px, sky} <- [{{1.0, 1.0}, {279.3407078819, 38.4201640697}}, {{750.5, 500.5}, {279.2610946856, 38.8033994608}}, {{1500.0, 1000.0}, {279.1803068890, 39.1869180445}}] do
      assert arcsec(Wcs.sky(@copy, px), sky) < 0.01
    end
  end

  test "carried onto the 6,000 px JPEG it lands where a solve of the full picture does" do
    full = Wcs.scale(@copy, 4.0, {6000, 4000})
    h = Map.new(full)
    assert {h["IMAGEW"], h["IMAGEH"]} == {6000, 4000}
    assert_in_delta h["CRPIX1"], (224.958896637 - 0.5) * 4 + 0.5, 1.0e-9
    assert_in_delta h["CD1_1"], 0.000177939491145 / 4, 1.0e-15
    assert_in_delta h["A_2_0"], 3.40811218986e-07 / 4, 1.0e-18
    assert h["A_ORDER"] == 2

    # the same sky through the copy's pixel and the full picture's
    for {x, y} <- [{1.0, 1.0}, {3000.5, 2000.5}, {6000.0, 4000.0}, {123.0, 3456.0}] do
      copy_px = {(x - 0.5) / 4 + 0.5, (y - 0.5) / 4 + 0.5}
      assert arcsec(Wcs.sky(full, {x, y}), Wcs.sky(@copy, copy_px)) < 0.01
    end

    # and where solve-field put the same pixels solving the 6,000 x 4,000 picture itself (wcs-xy2rd
    # on that solve): within a pixel and a half of the full picture (0.39 arcsec each)
    for {px, sky} <- [{{1.0, 1.0}, {279.3408326235, 38.4197439377}}, {{6000.0, 4000.0}, {279.1801837533, 39.1873826370}}, {{500.0, 3500.0}, {278.9298489382, 38.6242846951}}] do
      assert arcsec(Wcs.sky(full, px), sky) < 1.5
    end
  end

  test "no WCS in a header is nil" do
    assert Wcs.from_header([{"SIMPLE", true}, {"NAXIS", 0}]) == nil
  end
end
