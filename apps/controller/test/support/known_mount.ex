defmodule Controller.Test.KnownMount do
  @moduledoc """
  A mount whose truth is known, for tests of the one thing an alignment
  cannot see: which side the counterweight is on.

  The mount is an ideal one (polar axis on the pole) whose home was never
  set, so its counts run from wherever it woke: `off_ra` is how far its RA
  axis stood from the meridian then, in degrees, west positive. That is
  where the simulator still stands when a test begins. Its counterweight is
  below level east of the meridian (`cw: 1`): at `off_ra: -60` it hangs well
  down, at `off_ra: 4` the bar is all but level.

      truth = KnownMount.align(id, -60.0, [-2.0, 3.0, 5.0, 8.0])

  takes a plate with the RA axis at each of those turns from the meridian
  (those four all have the counterweight bar within 10° of level), hands
  them to `Lineup` the way Align by Photo does, and returns the true model,
  to hold against what the fit and the guess made of it.
  """

  alias Controller.Sky.{Astro, Lineup, Model, Pointing}

  @signs %{ha_sign: 1, dec_sign: -1}
  # off the pole, so the pose the simulator wakes in points at a patch of sky a hold can follow
  @off_dec 50.0
  # how far from the pole each plate's tube was, in turn
  @pole_distances [30.0, 45.0, 60.0, 75.0]

  def align(id, off_ra, turns) do
    # another test's alignment may have corrected the signs: these plates are made under these.
    # And they go back afterwards: left flipped, the next module's solves land below the horizon.
    unless Process.get({__MODULE__, :pointing_saved}) do
      Process.put({__MODULE__, :pointing_saved}, true)
      was = Controller.Settings.get("pointing")
      ExUnit.Callbacks.on_exit(fn -> Controller.Settings.put("pointing", was) end)
    end

    Controller.Settings.put("pointing", %{"ha_sign" => @signs.ha_sign, "dec_sign" => @signs.dec_sign})
    site = Pointing.site()
    now = DateTime.utc_now()
    lst = Astro.lst_deg(now, site.lon)
    truth = %{Model.ideal(site.lat) | off_ra: off_ra / 1, off_dec: @off_dec}

    plates =
      for {h, d} <- Enum.zip(turns, Stream.cycle(@pole_distances)) do
        theta_ra = (h - truth.off_ra) / @signs.ha_sign
        theta_dec = (d - truth.off_dec) / @signs.dec_sign
        {alt, az} = Model.altaz(truth, @signs, theta_ra, theta_dec)
        {ra, dec} = Astro.radec_from_altaz(alt, az, site.lat, lst)
        # the shape a solved plate is handed over in (`Controller.Plates`)
        %{"name" => "plate at #{h}", "at" => DateTime.to_iso8601(now), "theta_ra" => theta_ra, "theta_dec" => theta_dec, "ra_deg" => ra, "dec_deg" => dec, "alt" => alt, "az" => az}
      end

    Lineup.replace(id, plates, nil)
    Map.merge(truth, %{signs: @signs, cw: 1})
  end

  @doc "An object `ha` degrees past the meridian right now (negative: east of it)."
  def at_ha(ha, dec \\ 20.0) do
    lst = Astro.lst_deg(DateTime.utc_now(), Pointing.site().lon)
    %{id: "ha#{ha}", name: "Target #{ha}", ra_deg: Astro.norm360(lst - ha), dec_deg: dec}
  end
end
