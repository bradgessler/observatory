defmodule Controller.Sky.LineupTest do
  @moduledoc "The line-up against a simulated mount whose true geometry we control through the samples."
  use ExUnit.Case, async: false

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars}

  @id "sim-lineup"

  setup do
    Lineup.clear(@id)
    on_exit(fn -> Lineup.clear(@id) end)
    :ok
  end

  # a fake snapshot: the encoders a mount with `truth` would show while centred on `name`
  defp snap_on(truth, name, now) do
    s = Enum.find(Stars.all(), &(&1.name == name))
    site = Pointing.site()
    {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, Astro.lst_deg(now, site.lon))
    {r, d} = Model.encoders(truth, Pointing.pointing(), alt, az)
    {%{id: @id, homed: true, connected: true, tracking: :off, axes: %{ra: %{degrees: r}, dec: %{degrees: d}}}, s}
  end

  test "one star is a sync, three stars are a model, and the context picks it up" do
    truth = %{axis_alt: 30.0, axis_az: 60.0, off_ra: 8.0, off_dec: -3.0}
    now = ~U[2026-09-20 05:30:00Z]

    {snap, vega} = snap_on(truth, "Vega", now)
    st = Lineup.add(snap, vega, now)
    assert st.n == 1 and st.solved?
    assert st.rms_arcmin < 0.1

    for name <- ["Altair", "Arcturus"] do
      {snap, star} = snap_on(truth, name, now)
      Lineup.add(snap, star, now)
    end

    st = Lineup.status(@id)
    assert st.n == 3
    assert st.rms_arcmin < 0.1
    assert_in_delta st.axis_off_deg, Model.axis_error(truth, Pointing.site().lat), 0.2
    assert "deep sky" in st.good_for
    assert st.axis_words =~ "from the pole"

    ctx = Pointing.context(now, @id)
    assert Pointing.lined_up?(ctx)

    # a goto target through the context lands on the true mount
    saturn = %{name: "Saturn", ra_deg: 352.0, dec_deg: -8.0}
    {r, d} = Pointing.axes_for(saturn, ctx)
    {alt_true, az_true} = Model.altaz(truth, Pointing.pointing(), r, d)
    {alt, az} = Astro.alt_az(saturn.ra_deg, saturn.dec_deg, Pointing.site().lat, Astro.lst_deg(now, Pointing.site().lon))
    assert Astro.separation(Astro.altaz_vec(alt, az), Astro.altaz_vec(alt_true, az_true)) * 60 < 1.0

    # and the readout goes the other way
    {snap, _} = snap_on(truth, "Deneb", now)
    {ra, dec} = Pointing.scope_radec(snap, ctx)
    deneb = Enum.find(Stars.all(), &(&1.name == "Deneb"))
    assert Astro.separation_radec(ra, dec, deneb.ra_deg, deneb.dec_deg) * 60 < 1.0
  end

  test "candidates are bright, up, unused and spread out; guesses name the nearest star" do
    now = ~U[2026-09-20 05:30:00Z]
    ctx = Pointing.context(now, @id)
    cands = Lineup.candidates(@id, ctx)
    assert cands != []
    assert Enum.all?(cands, &(&1.alt > 20 and &1.mag <= 2.2))
    assert Enum.all?(cands, &is_binary(&1.where))

    truth = Model.ideal(Pointing.site().lat)
    {snap, vega} = snap_on(truth, "Vega", now)
    Lineup.add(snap, vega, now)
    refute Enum.any?(Lineup.candidates(@id, Pointing.context(now, @id)), &(&1.name == "Vega"))

    {snap, _} = snap_on(truth, "Altair", now)
    [g | _] = Lineup.guess(snap, Pointing.context(now, @id))
    assert g.name == "Altair"
    assert g.away_deg < 0.5
  end

  test "dropping a sample refits; clearing removes the model" do
    now = ~U[2026-09-20 05:30:00Z]
    truth = Model.ideal(Pointing.site().lat)
    for name <- ["Vega", "Altair"], {snap, star} = snap_on(truth, name, now), do: Lineup.add(snap, star, now)
    assert Lineup.status(@id).n == 2
    Lineup.drop(@id, 0)
    assert Lineup.status(@id).n == 1
    Lineup.clear(@id)
    refute Lineup.status(@id).solved?
    refute Pointing.lined_up?(Pointing.context(now, @id))
  end

  test "a wrong axis sign is found and corrected from three stars" do
    now = ~U[2026-09-20 05:30:00Z]
    truth = %{axis_alt: 40.0, axis_az: 10.0, off_ra: 3.0, off_dec: -2.0}
    configured = Pointing.pointing()
    # the mount is really wired with the opposite Dec sense
    wrong = %{configured | dec_sign: -configured.dec_sign}
    site = Pointing.site()

    for name <- ["Vega", "Altair", "Arcturus"] do
      s = Enum.find(Stars.all(), &(&1.name == name))
      {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, site.lat, Astro.lst_deg(now, site.lon))
      {r, d} = Model.encoders(truth, wrong, alt, az)
      Lineup.add(%{id: @id, homed: true, connected: true, tracking: :off, axes: %{ra: %{degrees: r}, dec: %{degrees: d}}}, s, now)
    end

    st = Lineup.status(@id)
    assert st.signs_corrected?
    assert st.rms_arcmin < 0.5
    assert Pointing.pointing() == wrong
    Settings.put("pointing", %{"ha_sign" => configured.ha_sign, "dec_sign" => configured.dec_sign})
  end

  test "where_words are for people" do
    assert Lineup.where_words(60, 90) == "high in the east"
    assert Lineup.where_words(15, 225) == "low in the south-west"
    assert Lineup.where_words(85, 0) == "nearly overhead"
  end
end
