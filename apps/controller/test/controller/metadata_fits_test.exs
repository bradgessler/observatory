defmodule Controller.Metadata.FitsTest do
  @moduledoc """
  The one keyword map: a frame's facts as the FITS cards every astronomy program reads, the same
  for the stills' sidecar and the telescope camera's files. Lick Observatory stands in for the site.
  """
  use ExUnit.Case, async: true

  alias Controller.Fits, as: File
  alias Controller.Metadata.{Fits, Sensor}

  @lick %{lat: 37.34, lon: -121.64, elevation_m: 1283.0}
  @t0 ~U[2026-10-18 03:21:39.655Z]

  # a light frame of M27 through the a6000, the mount pointing a little off the target
  defp facts(more \\ %{}) do
    sensor = Sensor.profile("ILCE-6000")

    Map.merge(
      %{
        type: :light,
        began: @t0,
        exposure_s: 15.0,
        object: %{id: "m27", name: "M27 Dumbbell Nebula", ra_deg: 299.9016, dec_deg: 22.7211},
        pointing: %{ra_deg: 300.1, dec_deg: 22.9, source: "star alignment"},
        site: @lick,
        instrument: Fits.instrument_name("Sony Corporation", "ILCE-6000"),
        telescope: "Explore Scientific ED102",
        observer: "An Observer",
        focal_length_mm: 714,
        aperture_mm: 102,
        pixel_um: sensor.pixel_um,
        binning: 1,
        cfa: sensor.cfa,
        iso: 1600,
        software: Fits.software_name("6f8be93d-56eb-5932-b78b-cbb570050d46"),
        ours: [{"OBS FRAME WHY", "light"}]
      },
      more
    )
  end

  test "a light frame's cards: standard names, the target in OBJCTRA, the pointing in RA, ours last" do
    cards = Fits.cards(facts())
    h = Map.new(cards, fn c -> {elem(c, 0), elem(c, 1)} end)
    keys = Enum.map(cards, &elem(&1, 0))

    assert h["IMAGETYP"] == "LIGHT"
    assert h["DATE-OBS"] == @t0 and h["TIMESYS"] == "UTC"
    assert h["DATE-END"] == ~U[2026-10-18 03:21:54.655Z] and h["DATE-AVG"] == ~U[2026-10-18 03:21:47.155Z]
    # MJD of 2026-10-18 03:21:39.655 UTC
    assert_in_delta h["MJD-OBS"], 61331.140042, 1.0e-6
    assert h["EXPTIME"] == 15.0 and h["EXPOSURE"] == 15.0
    assert h["INSTRUME"] == "Sony ILCE-6000" and h["TELESCOP"] == "Explore Scientific ED102" and h["OBSERVER"] == "An Observer"
    assert h["FOCALLEN"] == 714.0 and h["APTDIA"] == 102.0 and h["FOCRATIO"] == 7.0
    assert h["XPIXSZ"] == 3.92 and h["XBINNING"] == 1 and h["BAYERPAT"] == "RGGB" and h["ISOSPEED"] == 1600
    assert h["SITELAT"] == 37.34 and h["SITELONG"] == -121.64 and h["SITEELEV"] == 1283.0
    # the target's catalogue place in the sexagesimal cards, SIMBAD's name in OBJECT
    assert h["OBJECT"] == "M 27"
    assert h["OBJCTRA"] == "19 59 36.4" and h["OBJCTDEC"] == "+22 43 16"
    # where the mount pointed in RA/DEC, never in OBJCTRA
    assert h["RA"] == 300.1 and h["DEC"] == 22.9
    assert h["RADESYS"] == "ICRS" and h["EQUINOX"] == 2000.0
    assert is_number(h["CENTALT"]) and is_number(h["AIRMASS"]) and is_number(h["OBJCTHA"])
    assert h["SWCREATE"] =~ ~r/\AObservatory .* \(firmware 6f8be93d\)\z/
    # standard first, ours after
    assert Enum.find_index(keys, &(&1 == "OBS FRAME WHY")) > Enum.find_index(keys, &(&1 == "SWCREATE"))
    # each keyword once: one RADESYS, though the target and the pointing both ask for it
    assert Enum.count(keys, &(&1 == "RADESYS")) == 1
    assert keys == Enum.uniq(keys)
  end

  test "unknown is absent: no pointing, no site, no lens, no target" do
    cards = Fits.cards(%{type: :snapshot, began: @t0, exposure_s: 2.0})
    keys = Enum.map(cards, &elem(&1, 0))
    assert "IMAGETYP" in keys and "DATE-OBS" in keys
    for k <- ~w(RA DEC OBJECT OBJCTRA SITELAT FOCRATIO AIRMASS RADESYS TELESCOP), do: refute(k in keys, k)
    assert Map.new(cards, &{elem(&1, 0), elem(&1, 1)})["IMAGETYP"] == "SNAPSHOT"
  end

  test "IMAGETYP for each kind of frame" do
    assert Enum.map([:light, :dark, :flat, :bias, :snapshot, "dark", nil], &Fits.imagetyp/1) == ["LIGHT", "DARK", "FLAT", "BIAS", "SNAPSHOT", "DARK", nil]
  end

  test "the sidecar's block: keyword to value, in order, times as FITS writes them" do
    json = facts() |> Fits.cards() |> Fits.json() |> Jason.encode!() |> Jason.decode!(objects: :ordered_objects)
    [{first, _} | _] = json.values
    assert first == "IMAGETYP"
    assert json["DATE-OBS"] == "2026-10-18T03:21:39.655"
    assert json["OBJECT"] == "M 27" and json["OBS FRAME WHY"] == "light"
  end

  test "the same cards make a FITS header any reader takes, and read back" do
    cards = Fits.cards(facts())
    bin = File.encode(%{w: 2, h: 2, px: <<0, 1, 2, 3>>}, cards)
    {:ok, %{header: header}} = File.read(bin)
    h = Map.new(header)
    assert h["OBJECT"] == "M 27" and h["OBJCTRA"] == "19 59 36.4" and h["RA"] == 300.1
    assert h["DATE-OBS"] == "2026-10-18T03:21:39.655" and h["OBS FRAME WHY"] == "light"
    assert rem(byte_size(bin), 2880) == 0
  end

  test "airmass stays finite at the horizon (Kasten and Young), and is nil below it" do
    assert_in_delta Fits.airmass(90), 1.0, 0.001
    assert_in_delta Fits.airmass(30), 1.995, 0.01
    assert Fits.airmass(0.5) < 40
    assert Fits.airmass(-1) == nil
  end

  test "names SIMBAD resolves, from the catalogue's ids" do
    assert Fits.simbad_name("m27", "M27 Dumbbell Nebula") == "M 27"
    assert Fits.simbad_name("ngc6853", "x") == "NGC 6853"
    assert Fits.simbad_name("ic434", "x") == "IC 434"
    assert Fits.simbad_name("hip32349", "Sirius") == "HIP 32349"
    assert Fits.simbad_name("saturn", "Saturn") == "Saturn"
    assert Fits.simbad_name(nil, "Somewhere") == "Somewhere"
  end

  test "sexagesimal places round the way they read" do
    assert Fits.hms(0.0) == "00 00 00.0"
    assert Fits.hms(359.9999999) == "00 00 00.0"
    assert Fits.dms(-5.3900) == "-05 23 24"
    assert Fits.dms(22.99999) == "+23 00 00"
  end

  test "a camera's name for INSTRUME, and the sensor by model" do
    assert Fits.instrument_name("Sony Corporation", "ILCE-6000") == "Sony ILCE-6000"
    assert Fits.instrument_name(nil, "SVBONY SV105C") == "SVBONY SV105C"
    assert %{pixel_um: 3.92, cfa: "RGGB", w_px: 6000, raw_w_px: 6024} = Sensor.profile("ILCE-6000")
    assert %{pixel_um: 2.9} = Sensor.profile("SVBONY SV105C")
    assert Sensor.profile("Something else") == nil
  end
end
