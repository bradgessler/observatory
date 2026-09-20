defmodule Controller.Sim.TruthTest do
  @moduledoc """
  The simulator's hidden geometry. It decides where a simulated tube really
  points, and it must never reach the software that is supposed to discover it.
  """
  use ExUnit.Case, async: false

  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars}

  setup do
    id = "sim-truth-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    Lineup.clear(id)
    on_exit(fn -> Lineup.clear(id) end)
    %{id: id}
  end

  test "only simulated mounts have one" do
    assert Truth.sim?("sim-eq")
    refute Truth.sim?("cu.usbserial-AR7QY85A")
    assert Truth.get("sim-eq")
    refute Truth.get("cu.usbserial-AR7QY85A")
  end

  test "a badly set down mount is not pointing where the software thinks", %{id: id} do
    Truth.put(id, Truth.default(Pointing.site().lat))
    snap = Mount.snapshot(id)
    now = DateTime.utc_now()
    ctx = Pointing.context(now, id)

    %{ra_deg: tra, dec_deg: tdec, source: :truth} = Truth.looking_at(snap, ctx)
    {bra, bdec} = Pointing.scope_radec(snap, ctx)

    # a few degrees of polar error and an offset put the belief well off the truth
    apart = Astro.separation_radec(tra, tdec, bra, bdec)
    assert apart > 1.0, "the truth and the belief should differ, they are #{apart}° apart"
    assert apart < 20.0
  end

  test "a perfectly set down mount agrees with the software", %{id: id} do
    Truth.put(id, Truth.ideal(Pointing.site().lat))
    snap = Mount.snapshot(id)
    ctx = Pointing.context(DateTime.utc_now(), id)

    %{ra_deg: tra, dec_deg: tdec} = Truth.looking_at(snap, ctx)
    {bra, bdec} = Pointing.scope_radec(snap, ctx)
    assert Astro.separation_radec(tra, tdec, bra, bdec) < 0.01
  end

  test "a real mount falls back to the model's belief and says so", %{id: id} do
    snap = %{Mount.snapshot(id) | id: "cu.usbserial-XYZ"}
    ctx = Pointing.context(DateTime.utc_now(), id)
    assert %{source: :model} = Truth.looking_at(snap, ctx)
  end

  test "encoders_for lands the truth on a star, which is what a hand at the eyepiece does", %{id: id} do
    Truth.put(id, Truth.default(Pointing.site().lat))
    star = Enum.find(Stars.all(), &(&1.name == "Vega"))
    now = DateTime.utc_now()

    {r, d} = Truth.encoders_for(id, star.ra_deg, star.dec_deg, now)
    snap = Mount.snapshot(id)
    posed = %{snap | axes: %{snap.axes | ra: %{snap.axes.ra | degrees: r}, dec: %{snap.axes.dec | degrees: d}}}

    %{ra_deg: ra, dec_deg: dec} = Truth.looking_at(posed, Pointing.context(now, id))
    assert Astro.separation_radec(ra, dec, star.ra_deg, star.dec_deg) < 0.05
  end

  test "the truth never reaches the fit: the model is discovered, not told", %{id: id} do
    truth = %{axis_alt: Pointing.site().lat + 3.0, axis_az: 4.0, off_ra: 2.0, off_dec: -1.0}
    Truth.put(id, truth)
    now = DateTime.utc_now()
    site = Pointing.site()
    lst = Astro.lst_deg(now, site.lon)

    # three stars, each centred the way a person would: move until the truth
    # says the tube is on it, then tell the software "that's it"
    for name <- ["Vega", "Altair", "Arcturus"] do
      star = Enum.find(Stars.all(), &(&1.name == name))
      {alt, az} = Astro.alt_az(star.ra_deg, star.dec_deg, site.lat, lst)
      {r, d} = Model.encoders(truth, Pointing.pointing(), alt, az)
      snap = Mount.snapshot(id)
      posed = %{snap | axes: %{snap.axes | ra: %{snap.axes.ra | degrees: r}, dec: %{snap.axes.dec | degrees: d}}}
      Lineup.add(posed, star, now)
    end

    fitted = Lineup.model(id)
    assert_in_delta fitted.axis_alt, truth.axis_alt, 0.3
    assert abs(Astro.norm180(fitted.axis_az - truth.axis_az)) < 0.5
    assert Lineup.status(id).rms_arcmin < 5.0
  end
end
