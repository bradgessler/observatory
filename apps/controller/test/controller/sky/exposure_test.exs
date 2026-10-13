defmodule Controller.Sky.ExposureTest do
  @moduledoc """
  A starting exposure per target (#117). "The targets have known magnitudes.
  Saturn's bright. You could work out what the camera exposure and ISO should
  be": for the Moon and planets it follows from surface brightness, f-ratio
  and ISO, and the numbers are held to the night they were found by hand
  (3 October 2026, the a6000 on the 8SE at f/10); for deep sky the limit is
  how long the mount holds a star round, so the advice is the longest
  untrailed shutter, a high ISO and a number of frames.
  """
  use ExUnit.Case, async: false

  alias Controller.Settings
  alias Controller.Sky.{Catalog, Ephemeris, Exposure}

  # the 8SE: 203.2 mm at f/10
  @f10 [aperture_mm: 203.2, focal_length_mm: 2032]
  @f5 [aperture_mm: 203.2, focal_length_mm: 1016]
  @shutters ~w(1/1000 1/250 1/60 1/15 1/4 1 4 15 30)

  defp body(id), do: Enum.find(Ephemeris.objects(~U[2026-10-12 05:00:00Z]), &(&1.id == id))
  defp moon, do: body("sol-moon")
  defp saturn, do: body("sol-saturn")
  defp jupiter, do: body("sol-jupiter")
  defp vega, do: Catalog.star("hip91262")
  defp m31, do: Catalog.dso("m31")
  defp m57, do: Catalog.dso("m57")

  describe "the Moon and the planets, from surface brightness and the f-ratio" do
    test "a full Moon is Looney 11: at f/10 and ISO 800, 1/1000 s" do
      a = Exposure.advise(moon(), @f10 ++ [iso: 800, illumination: 1.0])
      assert %{iso: 800, shutter: "1/1000", rule: :surface, confidence: :known, frames: nil} = a
      # f/11 at 1/ISO, so at f/10: (10/11)² / 800
      assert_in_delta a.ideal_s, 100 / 121 / 800, 1.0e-9
      assert_in_delta a.f_ratio, 10.0, 1.0e-9
      assert a.why =~ "Looney 11 at f/10"
    end

    test "a quarter Moon gets a stop more: 1/60 s at ISO 100, as it was taken on 3 October" do
      assert %{iso: 100, shutter: "1/60", confidence: :known} = a = Exposure.advise(moon(), @f10 ++ [iso: 100, illumination: 0.5])
      assert a.why =~ "one stop more for a quarter Moon"
      # a crescent two stops, a gibbous Moon half a stop
      full = Exposure.advise(moon(), @f10 ++ [iso: 100, illumination: 1.0]).ideal_s
      assert_in_delta Exposure.advise(moon(), @f10 ++ [iso: 100, illumination: 0.2]).ideal_s, full * 4, 1.0e-9
      assert_in_delta Exposure.advise(moon(), @f10 ++ [iso: 100, illumination: 0.8]).ideal_s, full * :math.sqrt(2), 1.0e-9
    end

    test "the Moon with no phase given is taken as full, and says it is rough" do
      a = Exposure.advise(moon(), @f10 ++ [iso: 800])
      assert %{shutter: "1/1000", confidence: :rough} = a
      assert a.why =~ "taken as a full Moon"
    end

    test "Saturn at f/10 and ISO 800 is 1/60 s: the equation asks for 1/42, and 1/40 is what the night used" do
      a = Exposure.advise(saturn(), @f10 ++ [iso: 800])
      assert %{iso: 800, shutter: "1/60", rule: :surface, confidence: :known} = a
      assert_in_delta 1 / a.ideal_s, 42, 2
      assert a.why == "From the surface brightness of Saturn, 6.8 mag per square arcsecond, at f/10."
      # half a stop under what the equation asks: the nearest shutter the camera offers
      assert_in_delta a.off_stops, -0.5, 0.1
      assert a.range == {"1/60", "1/15"}
    end

    test "Jupiter is brighter per square arcsecond than Saturn: a shorter shutter, 1/250 s" do
      a = Exposure.advise(jupiter(), @f10 ++ [iso: 800])
      assert %{iso: 800, shutter: "1/250", confidence: :known} = a
      assert a.ideal_s < Exposure.advise(saturn(), @f10 ++ [iso: 800]).ideal_s / 3
    end

    test "with no ISO given, the ISO and shutter are chosen together from what the camera offers" do
      assert %{iso: 800, shutter: "1/60"} = Exposure.advise(saturn(), @f10)
      assert %{iso: 100, shutter: "1/60"} = Exposure.advise(moon(), @f10 ++ [illumination: 0.5])
      # a full Moon at ISO 100 falls between 1/60 and 1/250: a higher ISO lands on it
      a = Exposure.advise(moon(), @f10 ++ [illumination: 1.0])
      assert a.iso in Exposure.isos() and a.shutter in @shutters
      assert abs(a.off_stops) < 0.25
    end

    test "between two shutter speeds it leans dark: a clipped disc is lost, a dark one can be brightened" do
      # a full Moon at ISO 100 asks for 1/121, a stop from both 1/60 and 1/250
      a = Exposure.advise(moon(), @f10 ++ [iso: 100, illumination: 1.0])
      assert_in_delta 1 / a.ideal_s, 121, 0.001
      assert a.shutter == "1/250" and a.off_stops < 0
      # the range still reaches a stop either side
      assert a.range == {"1/250", "1/60"}
    end

    test "the f-ratio changes the answer: two stops faster at f/5" do
      slow = Exposure.advise(saturn(), @f10 ++ [iso: 800])
      fast = Exposure.advise(saturn(), @f5 ++ [iso: 800])
      assert_in_delta fast.ideal_s, slow.ideal_s / 4, 1.0e-9
      assert fast.shutter_s < slow.shutter_s
      assert fast.why =~ "at f/5."
      # the f-ratio itself is a knob too
      assert_in_delta Exposure.advise(saturn(), f_ratio: 5, iso: 800).ideal_s, fast.ideal_s, 1.0e-9
    end

    test "too bright for the fastest shutter at the ISO given: it says to lower the ISO" do
      venus = body("sol-venus")
      a = Exposure.advise(venus, @f10 ++ [iso: 800])
      assert a.shutter == "1/1000" and a.off_stops > 2
      assert a.why =~ "stops over at the fastest shutter: use a lower ISO."
      # left to choose, it does
      assert %{iso: 100, shutter: "1/1000"} = b = Exposure.advise(venus, @f10)
      refute b.why =~ "stops over"
    end

    test "with no optics given it assumes f/10, says so, and is rough" do
      a = Exposure.advise(saturn(), iso: 800)
      assert %{shutter: "1/60", confidence: :rough} = a
      assert a.why =~ "Assumes f/10"
    end

    test "a planet with no surface brightness on file gets a middling one, marked rough" do
      a = Exposure.advise(%{id: "sol-pluto", name: "Pluto", kind: :planet, mag: 14.0}, @f10)
      assert a.confidence == :rough
      assert a.why =~ "No surface brightness on file for Pluto"
    end
  end

  describe "a star" do
    test "Vega: a short shutter for a round star, not a deep exposure" do
      a = Exposure.advise(vega(), @f10 ++ [iso: 800])
      assert %{iso: 800, shutter: "1/1000", rule: :star, confidence: :rough} = a
      assert a.why =~ "round and unclipped at f/10. Not a deep exposure."
    end

    test "a fainter star takes longer, a wider star takes longer, and a slower telescope takes longer" do
      vega = Exposure.advise(vega(), @f10 ++ [iso: 800])
      faint = Exposure.advise(%{vega() | mag: 5.0}, @f10 ++ [iso: 800])
      assert_in_delta faint.ideal_s / vega.ideal_s, :math.pow(10, 0.4 * (5.0 - vega().mag)), 1.0e-6
      assert Exposure.advise(vega(), @f10 ++ [iso: 800, star_arcsec: 10]).ideal_s > vega.ideal_s * 3.9
      assert Exposure.advise(vega(), @f5 ++ [iso: 800]).ideal_s < vega.ideal_s
    end
  end

  describe "deep sky: the longest untrailed shutter, a high ISO, frames to stack" do
    test "M31: 15 s at ISO 3200, the default limit named as one" do
      a = Exposure.advise(m31(), @f10)
      assert %{iso: 3200, shutter: "15", shutter_s: 15.0, rule: :deep, confidence: :rough, max_from: :default, ideal_s: nil} = a
      assert a.frames == 20
      assert a.range == {"4", "15"}
      assert a.why == "The longest shutter under the 15 s default tracking limit at ISO 3200, 20 frames to stack. Sky glow and tracking set this, not its magnitude."
    end

    test "M57 is small and bright per area: the same shutter, fewer frames" do
      a = Exposure.advise(m57(), @f10)
      assert %{iso: 1600, shutter: "15", rule: :deep, ease: :easy, frames: 8} = a
      # a big faint galaxy is hard, and gets the most
      assert %{ease: :hard, frames: 40} = Exposure.advise(Catalog.dso("m33"), @f10)
      assert %{ease: :medium} = Exposure.advise(m31(), @f10)
    end

    test "its magnitude does not set the shutter" do
      assert Exposure.advise(%{m31() | mag: 9.5}, @f10).shutter == Exposure.advise(m31(), @f10).shutter
    end

    test "the f-ratio does not change the deep-sky rule" do
      for obj <- [m31(), m57()] do
        assert Exposure.advise(obj, @f10) == Exposure.advise(obj, @f5)
        assert Exposure.advise(obj, @f10) == Exposure.advise(obj, [])
      end
    end

    test "the ISO given is kept" do
      assert %{iso: 6400, shutter: "15"} = Exposure.advise(m31(), @f10 ++ [iso: 6400])
    end

    test "an object the catalogue has no size for is ranked by its kind" do
      assert %{ease: :hard} = Exposure.advise(%{id: "x", name: "X", kind: :galaxy, mag: 9.0}, [])
      assert %{ease: :easy} = Exposure.advise(%{id: "x", name: "X", kind: :planetary, mag: 9.0}, [])
    end
  end

  describe "the limit on the shutter" do
    test "max_s is respected: nothing longer comes back, for any kind" do
      assert %{shutter: "4", max_from: :given, confidence: :known} = a = Exposure.advise(m31(), @f10 ++ [max_s: 5])
      assert a.why =~ "under the 5 s tracking limit"
      assert %{shutter: "30"} = Exposure.advise(m31(), @f10 ++ [max_s: 60])

      for obj <- [moon(), saturn(), jupiter(), vega(), m31(), m57()], max <- [0.5, 2, 5, 20, 40] do
        a = Exposure.advise(obj, @f10 ++ [max_s: max])
        assert a.shutter_s <= max
        {_, slower} = a.range
        assert Controller.StillCamera.Sidecar.seconds(slower) <= max
      end
    end

    # the issue's own test
    test "drift 0.1 arcsec/s and stars 5 arcsec wide: the suggestion for a galaxy is not over 20 s" do
      assert Exposure.untrailed_s(0.1, 5.0) == 20.0
      a = Exposure.advise(m31(), @f10 ++ [drift_arcsec_s: 0.1, star_arcsec: 5.0])
      assert a.shutter_s <= 20
      assert %{shutter: "15", max_from: :drift, confidence: :known} = a
      assert a.why =~ "the measured drift (0.10 arcsec/s) keeps round, 20 s or less"
      # twice the drift, half the time
      assert %{shutter: "4"} = Exposure.advise(m31(), @f10 ++ [drift_arcsec_s: 0.2, star_arcsec: 5.0])
    end

    test "a faint star held short by the limit says how far under it is" do
      a = Exposure.advise(%{vega() | mag: 12.0}, @f10 ++ [iso: 100, max_s: 4])
      assert a.shutter == "4"
      assert a.why =~ "Held to 4 s by the tracking limit"
    end

    test "a limit shorter than every shutter gives the fastest one" do
      assert %{shutter: "1/1000"} = Exposure.advise(m31(), max_s: 0.0001)
    end
  end

  describe "what the camera offers" do
    test "the shutter and ISO returned are ones the camera offers" do
      mine = ~w(1/500 1/125 1/30 1/8 2 8 Bulb)

      for obj <- [moon(), saturn(), jupiter(), vega(), m31(), m57()], opts <- [[], [iso: 800], [max_s: 3], @f5] do
        a = Exposure.advise(obj, @f10 ++ opts)
        assert a.shutter in @shutters
        assert a.iso in [100, 400, 800, 1600, 3200, 6400]
        assert elem(a.range, 0) in @shutters and elem(a.range, 1) in @shutters

        b = Exposure.advise(obj, @f10 ++ opts ++ [shutters: mine, isos: [200, 1250]])
        assert b.shutter in mine and b.shutter != "Bulb"
        assert b.iso in [200, 1250, 800]
        assert b.shutter_s == Controller.StillCamera.Sidecar.seconds(b.shutter)
      end
    end
  end

  test "nothing for a kind it has no rule for" do
    assert Exposure.advise(%{id: "x", name: "X", kind: :comet, mag: 5.0}, @f10) == nil
    assert Exposure.advise(nil, @f10) == nil
    assert Exposure.tonight(nil) == nil
  end

  test "the advice in one line" do
    assert Exposure.words(Exposure.advise(saturn(), @f10 ++ [iso: 800])) == "ISO 800 · 1/60 s"
    assert Exposure.words(Exposure.advise(m31(), @f10)) == "ISO 3200 · 15 s · 20 frames"
    assert Exposure.range_words(Exposure.advise(saturn(), @f10 ++ [iso: 800])) == "1/60 to 1/15 s"
    assert Exposure.range_words(%{range: {"15", "15"}}) == nil
  end

  describe "tonight/2, with the telescope as it is set" do
    setup do
      was = {Settings.get("aperture_mm"), Settings.get("focal_length_mm")}

      on_exit(fn ->
        # never nil: Settings has no delete, and a nil left behind takes the place of the pages' default of 100
        Settings.put("aperture_mm", elem(was, 0) || 100)
        Settings.put("focal_length_mm", elem(was, 1))
      end)
    end

    test "the aperture and focal length in Settings give the f-ratio" do
      Settings.put("aperture_mm", 203.2)
      Settings.put("focal_length_mm", 2084)
      a = Exposure.tonight(saturn(), iso: 800)
      assert_in_delta a.f_ratio, 2084 / 203.2, 1.0e-9
      assert a.confidence == :known and a.why =~ "at f/10.3."
      # an option given wins
      assert_in_delta Exposure.tonight(saturn(), f_ratio: 7).f_ratio, 7.0, 1.0e-9
    end

    test "with either missing it assumes f/10 and says so" do
      Settings.put("aperture_mm", 203.2)
      Settings.put("focal_length_mm", nil)
      assert %{confidence: :rough, why: why} = Exposure.tonight(saturn())
      assert why =~ "Assumes f/10"
    end

    test "the Moon's phase comes from the ephemeris at the time asked about" do
      Settings.put("aperture_mm", 203.2)
      Settings.put("focal_length_mm", 2032)
      # 3 October 2026, the night of the ledger: a last-quarter Moon
      at = ~U[2026-10-03 10:00:00Z]
      assert Ephemeris.moon_phase(at).name =~ "last quarter"
      assert %{iso: 100, shutter: "1/60", confidence: :known} = Exposure.tonight(moon(), at: at)
    end
  end
end
