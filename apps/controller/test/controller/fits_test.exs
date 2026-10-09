defmodule Controller.FitsTest do
  @moduledoc """
  Frames are FITS files that astronomy software reads as it is: valid by
  the standard's own checker, standard keywords where there are some, ours
  by the HIERARCH convention, the picture the right way up, and a header
  that can grow after the fact.
  """
  use ExUnit.Case, async: true

  alias Controller.Fits

  @img %{w: 4, h: 3, px: <<1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12>>}

  defp tmp(name), do: Path.join(System.tmp_dir!(), "fits-#{System.unique_integer([:positive])}-#{name}")

  test "the picture and its header go in, and come back out the same" do
    at = ~U[2026-10-02 04:21:15.123Z]

    bin =
      Fits.encode(@img, [
        {"ROWORDER", "TOP-DOWN", "first row is the top of the picture"},
        {"DATE-OBS", at, "exposure start, UTC"},
        {"EXPTIME", 1.0, "seconds"},
        {"GAIN", 100},
        {"INSTRUME", "SVBONY SV105C · 1920×1080"},
        {"OBS CAMERA SHARPNESS", 0, "the camera's own sharpening, off"},
        {"OBS FRAME VERDICT", :no_stars},
        {"OBS UNKNOWN", nil},
        {"OBS QUOTE", "it's here"},
        {:comment, "Taken by the Observatory box."}
      ])

    assert rem(byte_size(bin), 2880) == 0
    {:ok, f} = Fits.read(bin)
    assert {f.w, f.h, f.px} == {4, 3, @img.px}
    h = Map.new(f.header)
    assert h["DATE-OBS"] == "2026-10-02T04:21:15.123"
    assert h["EXPTIME"] == 1.0
    assert h["GAIN"] == 100
    assert h["INSTRUME"] == "SVBONY SV105C - 1920x1080"
    assert h["OBS CAMERA SHARPNESS"] == 0
    assert h["OBS FRAME VERDICT"] == "no_stars"
    assert h["OBS QUOTE"] == "it's here"
    refute Map.has_key?(h, "OBS UNKNOWN")
    # every header line is 80 printable ASCII characters
    {:ok, _, size} = Fits.header_of(bin)
    assert binary_part(bin, 0, size) =~ ~r/\A[\x20-\x7e]+\z/
  end

  test "a bottom-up file (the FITS default) is read the right way up" do
    bin = Fits.encode(%{@img | px: <<9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4>>})
    {:ok, f} = Fits.read(bin)
    assert f.px == @img.px
  end

  test "cards can be added and replaced afterwards, in place or by growing the header" do
    path = tmp("u.fits")
    File.write!(path, Fits.encode(@img, [{"ROWORDER", "TOP-DOWN"}, {"OBS STARS", 0}]))
    size = File.stat!(path).size

    :ok = Fits.update(path, [{"OBS STARS", 7}, {"OBS HFR PX", 2.5}])
    assert File.stat!(path).size == size
    # the lines not replaced stay exactly as written, comments and all
    assert File.read!(path) =~ "ROWORDER= 'TOP-DOWN'"
    {:ok, f} = Fits.read(File.read!(path))
    h = Map.new(f.header)
    assert h["OBS STARS"] == 7 and h["OBS HFR PX"] == 2.5 and f.px == @img.px

    # 60 more cards don't fit the first block: the header grows a block, the pixels survive
    :ok = Fits.update(path, for(i <- 1..60, do: {"OBS EXTRA #{i}", i}))
    assert File.stat!(path).size == size + 2880
    {:ok, f} = Fits.read(File.read!(path))
    assert Map.new(f.header)["OBS EXTRA 60"] == 60 and f.px == @img.px
  end

  @tag :fitsverify
  test "the standard's own checker passes it" do
    exe = System.find_executable("fitsverify")
    if exe == nil, do: flunk("fitsverify isn't installed (brew install cfitsio)")
    path = tmp("v.fits")

    File.write!(
      path,
      Fits.encode(@img, [
        {"ROWORDER", "TOP-DOWN"},
        {"DATE-OBS", DateTime.utc_now()},
        {"EXPTIME", 0.5},
        {"OBS MOUNT RA DEG", 20.56, "encoder"},
        {"OBS CAMERA MODE", "raw 1920×1080"},
        {:history, "kept by the frames pipeline"}
      ])
    )

    {out, code} = System.cmd(exe, ["-q", path], stderr_to_stdout: true)
    assert code == 0, out
    assert out =~ "0 warnings and 0 errors" or out =~ "OK", out
  end
end
