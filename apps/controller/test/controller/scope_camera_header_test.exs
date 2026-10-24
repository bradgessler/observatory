defmodule Controller.ScopeCamera.HeaderTest do
  @moduledoc """
  The telescope camera's FITS header, from the shared keyword map (`Controller.Metadata.Fits`): the
  three things it used to misname (`TELESCOP` held the mount, `IMAGETYP` was always `LIGHT`,
  `OBJCTRA`/`OBJCTDEC` held the pointing) and what it was missing. Lick Observatory stands in for
  the site.
  """
  use ExUnit.Case, async: true

  alias Controller.ScopeCamera.Header

  @ended ~U[2026-10-18 03:21:40.000Z]

  defp header(record, ctx) do
    record = Map.merge(%{at: @ended, exposure_ms: 500, stack: 4, gain: 120, w: 960, seq: 7, why: "picture"}, record)

    ctx =
      Map.merge(
        %{
          ended_at: @ended,
          camera_name: "SVBONY SV105C",
          capture_size: {1920, 1080},
          site: %{lat: 37.34, lon: -121.64},
          pointing: {300.1, 22.9, "star alignment"},
          target: %{id: "m27", name: "M27 Dumbbell Nebula", ra_deg: 299.9016, dec_deg: 22.7211},
          mount: %{id: "ttyUSB0", start: nil, end: nil},
          model: %{n: 4, rms_arcmin: 0.77, stale?: false, axis_off_deg: 10.6, axis_alt_deg: 33.1, axis_az_deg: 348.2, axis_words: "polar axis 10.6° from the pole"},
          node: "telescope@observatory.local",
          firmware: "6f8be93d-56eb-5932-b78b-cbb570050d46"
        },
        ctx
      )

    record |> Header.cards(ctx) |> Enum.reject(&is_atom(elem(&1, 0))) |> Map.new(fn c -> {elem(c, 0), elem(c, 1)} end)
  end

  test "the mount is OBS MOUNT NAME, the target is OBJCTRA/OBJCTDEC, the pointing is RA/DEC" do
    h = header(%{}, %{})
    assert h["OBS MOUNT NAME"] == "EQ6-R (ttyUSB0)"
    refute Map.has_key?(h, "TELESCOP")
    assert h["OBJECT"] == "M 27" and h["OBJCTRA"] == "19 59 36.4" and h["OBJCTDEC"] == "+22 43 16"
    assert h["RA"] == 300.1 and h["DEC"] == 22.9 and h["RADESYS"] == "ICRS"
    assert h["OBS POINTING SOURCE"] == "star alignment"
  end

  test "IMAGETYP says what the frame is: a picture is LIGHT, live view is SNAPSHOT" do
    assert header(%{}, %{})["IMAGETYP"] == "LIGHT"
    assert header(%{why: "live view"}, %{})["IMAGETYP"] == "SNAPSHOT"
  end

  test "what was missing: MJD, the frame's middle, focal ratio, the pixel from the camera's profile, the polar axis in numbers" do
    h = header(%{}, %{})
    # 4 frames of 0.5 s before the grab ended
    assert h["DATE-OBS"] == ~U[2026-10-18 03:21:38.000Z] and h["DATE-END"] == @ended
    assert h["DATE-AVG"] == ~U[2026-10-18 03:21:39.000Z] and is_float(h["MJD-OBS"]) and h["TIMESYS"] == "UTC"
    assert h["EXPTIME"] == 0.5 and h["NCOMBINE"] == 4 and h["XPOSURE"] == 2.0
    # 1920 px read into a 960 px frame: 2 x 2, each 2.9 um pixel of the IMX307 made 5.8
    assert h["XBINNING"] == 2 and h["XPIXSZ"] == 5.8
    assert h["OBS MODEL AXIS OFF DEG"] == 10.6 and h["OBS MODEL AXIS ALT DEG"] == 33.1 and h["OBS MODEL AXIS AZ DEG"] == 348.2
    assert h["SWCREATE"] =~ "firmware 6f8be93d"
    assert h["ROWORDER"] == "TOP-DOWN"
  end

  test "no hold and no alignment: no target, no pointing, and it says so" do
    h = header(%{}, %{target: nil, pointing: nil})
    for k <- ~w(OBJECT OBJCTRA RA DEC RADESYS), do: refute(Map.has_key?(h, k), k)
    assert h["OBS POINTING SOURCE"] == "none: not homed or lined up"
  end
end
