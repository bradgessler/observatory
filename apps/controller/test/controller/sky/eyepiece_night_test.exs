defmodule Controller.Sky.EyepieceNightTest do
  @moduledoc """
  A whole night indoors, through the eyepiece: a mount set down badly, three
  stars centred by hand the way a person would, and then a goto that lands in
  the middle of the field.

  This is the epic's acceptance test. It uses only what a person can reach: the
  eyepiece's own view to see where the tube is, and gotos to move it. The
  software is never told the truth.
  """
  use ExUnit.Case, async: false

  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Catalog, Lineup, Pointing, Stars, Tracker}

  @moduletag timeout: 300_000

  setup do
    id = "sim-eyenight-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    Lineup.clear(id)
    Truth.put(id, %{axis_alt: Pointing.site().lat + 2.5, axis_az: 3.0, off_ra: 1.0, off_dec: -1.5})
    on_exit(fn -> Tracker.stop(id); Lineup.clear(id) end)
    %{id: id, ref: Enum.find(Mount.list(), &(&1.id == id))}
  end

  test "three stars centred through the eyepiece, then a goto that lands", %{id: id, ref: ref} do
    ctx = fn -> Pointing.context(DateTime.utc_now(), id) end

    # Star one: slew where the software believes the star is, and look.
    star = Enum.find(Stars.all(), &(&1.name == "Vega"))
    assert {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), star, ctx.(), track: false)
    settle(id)

    miss = off_centre(id, star, ctx.())
    assert miss > 0.5, "a badly set down mount should miss; it was #{miss}° off"

    # Centre it by hand, then the other two, and tell the software each time.
    for name <- ["Vega", "Altair", "Arcturus"] do
      s = Enum.find(Stars.all(), &(&1.name == name))
      centre_by_hand(id, ref, s)
      assert off_centre(id, s, ctx.()) < 0.05
      Lineup.add(Mount.snapshot(id), s)
    end

    status = Lineup.status(id)
    assert status.n == 3
    assert status.rms_arcmin < 5.0, "the three stars should agree; they were #{status.rms_arcmin}′ apart"

    # What it worked out should be the truth, without ever being told it.
    fitted = Lineup.model(id)
    truth = Truth.get(id)
    assert_in_delta fitted.axis_alt, truth.axis_alt, 0.4
    # an azimuth is an angle: 363° and 3° are the same heading
    assert abs(Astro.norm180(fitted.axis_az - truth.axis_az)) < 0.6

    # Now a goto through the fitted geometry lands in the eyepiece.
    target = Enum.find(Catalog.dsos(), &(&1.id == "m13")) || Enum.find(Stars.all(), &(&1.name == "Deneb"))
    assert {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), target, ctx.(), track: false)
    settle(id)

    landed = off_centre(id, target, ctx.())
    assert landed < 0.25, "after three stars a goto should land in the field; it was #{landed}° off"
  end

  # How far the tube really is from an object, in degrees: what the eyepiece draws.
  defp off_centre(id, obj, ctx) do
    %{ra_deg: ra, dec_deg: dec} = Truth.looking_at(Mount.snapshot(id), ctx)
    Astro.separation_radec(ra, dec, obj.ra_deg, obj.dec_deg)
  end

  # A person at the eyepiece: move until the star is in the middle. Twice,
  # because the first move is computed from where the mount was.
  defp centre_by_hand(id, ref, star) do
    for _ <- 1..2 do
      now = DateTime.utc_now()
      snap = Mount.snapshot(id)
      near = {snap.axes.ra.degrees, snap.axes.dec.degrees}

      case Truth.encoders_for(id, star.ra_deg, star.dec_deg, now, near) do
        {r, d} ->
          :ok = Mount.goto_relative(ref, :ra, r - snap.axes.ra.degrees)
          :ok = Mount.goto_relative(ref, :dec, d - snap.axes.dec.degrees)
          settle(id)

        _ ->
          :ok
      end
    end
  end

  defp settle(id, tries \\ 400) do
    s = Mount.snapshot(id)

    if (s.axes.ra.running or s.axes.dec.running or s.axes.ra.goto_pending or s.axes.dec.goto_pending) and tries > 0 do
      Process.sleep(250)
      settle(id, tries - 1)
    end
  end
end
