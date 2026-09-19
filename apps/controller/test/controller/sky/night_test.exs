defmodule Controller.Sky.NightTest do
  @moduledoc """
  The whole evening on the simulator, end to end through the real processes:
  a mount whose true geometry is hidden from the software, three named stars,
  then a goto to a planet through the sky page's path, then tracking.
  """
  use ExUnit.Case, async: false

  alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars, Tracker}

  # how the mount is *really* sitting tonight: 30° off in azimuth, latitude knob 6° high
  @truth %{axis_alt: 43.9, axis_az: 330.0, off_ra: 12.0, off_dec: -4.0}

  setup do
    id = "sim-night-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    Lineup.clear(id)
    on_exit(fn -> Tracker.stop(id); Lineup.clear(id) end)
    %{id: id, ref: Enum.find(Mount.list(), &(&1.id == id))}
  end

  # The person centres a star: on the real mount the encoders end up where the
  # true geometry puts them. We move the simulator there and say "that's it".
  # Two passes, like a person: a big move, then a small correction for the
  # arcminutes the star drifted while the mount was slewing.
  defp centre_on(ref, id, name) do
    star = Enum.find(Stars.all(), &(&1.name == name))
    site = Pointing.site()

    for _pass <- 1..2 do
      now = DateTime.utc_now()
      {alt, az} = Astro.alt_az(star.ra_deg, star.dec_deg, site.lat, Astro.lst_deg(now, site.lon))
      snap = Mount.snapshot(id)
      {r, d} = Model.encoders(@truth, Pointing.pointing(), alt, az, {snap.axes.ra.degrees, snap.axes.dec.degrees})
      :ok = Mount.goto_relative(ref, :ra, r - snap.axes.ra.degrees)
      :ok = Mount.goto_relative(ref, :dec, d - snap.axes.dec.degrees)
      settle(id)
    end

    Lineup.add(Mount.snapshot(id), star, DateTime.utc_now())
  end

  # landed = the gotos are done; the tracker may already be running the axes
  defp settle(id) do
    wait_until(fn -> s = Mount.snapshot(id); not s.axes.ra.goto_pending and not s.axes.dec.goto_pending and not s.axes.dec.running end, 90_000)
  end

  @tag timeout: 400_000
  test "three stars, then Saturn lands and tracks", %{id: id, ref: ref} do
    for name <- ["Vega", "Altair", "Arcturus"], do: centre_on(ref, id, name)

    st = Lineup.status(id)
    assert st.n == 3
    assert st.rms_arcmin < 1.0, "stars agree to #{st.rms_arcmin}′"
    assert_in_delta st.axis_off_deg, Model.axis_error(@truth, Pointing.site().lat), 0.5

    # Saturn tonight, through the same call the Sky page makes
    now = DateTime.utc_now()
    saturn = Enum.find(Controller.Sky.Ephemeris.objects(now), &(&1.name =~ "Saturn"))
    ctx = Pointing.context(now, id)
    assert Pointing.lined_up?(ctx)
    {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), saturn, ctx)
    settle(id)
    # a long goto lands where the target *was*; the tracker pulls it in
    wait_until(fn -> t = Tracker.status(id); t != nil and t.error_arcmin != nil and t.error_arcmin < 2.0 end, 60_000)

    # where the *real* mount points with the encoders it has now
    snap = Mount.snapshot(id)
    {alt_true, az_true} = Model.altaz(@truth, Pointing.pointing(), snap.axes.ra.degrees, snap.axes.dec.degrees)
    site = Pointing.site()
    {alt, az} = Astro.alt_az(saturn.ra_deg, saturn.dec_deg, site.lat, Astro.lst_deg(DateTime.utc_now(), site.lon))
    miss = Astro.separation(Astro.altaz_vec(alt, az), Astro.altaz_vec(alt_true, az_true)) * 60
    assert miss < 5.0, "Saturn missed by #{miss}′"

    # and the tracker is the one holding it
    tr = Tracker.status(id)
    assert tr.name =~ "Saturn"
    assert tr.error_arcmin < 3.0
    assert Mount.snapshot(id).tracking == :off
  end

  defp wait_until(fun, ms) do
    deadline = System.monotonic_time(:millisecond) + ms

    Stream.repeatedly(fn -> Process.sleep(100); fun.() end)
    |> Enum.find(fn ok -> ok or System.monotonic_time(:millisecond) > deadline end)
    |> then(fn ok -> assert ok, "timed out after #{ms} ms" end)
  end
end
