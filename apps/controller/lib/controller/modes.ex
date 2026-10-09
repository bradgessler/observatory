defmodule Controller.Modes do
  @moduledoc """
  Anything persistent that changes where the scope goes or how it behaves —
  the "trim" problem. If a mode is on, every page says so, in the same words,
  with a link to where it can be turned off.
  """

  alias Controller.Settings
  alias Controller.Sky.Pointing

  @doc "Active modes as `{label, detail}` pairs. Empty when everything is stock."
  def active do
    off = Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})
    p = Pointing.pointing()
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    [
      if(abs(off["ra"]) > 0.01 or abs(off["dec"]) > 0.01,
        do: {"Sync offset", "RA #{fmt(off["ra"])}° · Dec #{fmt(off["dec"])}°"}),
      if(p.ha_sign != base.ha_sign, do: {"RA axis flipped", "sign #{p.ha_sign}"}),
      if(p.dec_sign != base.dec_sign, do: {"Dec axis flipped", "sign #{p.dec_sign}"}),
      if(Settings.get("tracking_direction") == "reverse", do: {"Tracking reversed", "RA runs the other way"}),
      if(Settings.get("auto_track", true) == false, do: {"Auto-track off", "slews won't start tracking"}),
      site_mode(),
      mount_tilt_mode(),
      mount_heading_mode(),
      lineup_mode(),
      counterweight_mode(),
      axis_scan_mode(),
      lock_on_mode()
    ]
    |> Enum.reject(&is_nil/1)
  end

  # No site at all is the loudest: the sky and every Go To assume 0°, 0°.
  # A configured site replaced by hand or phone is an override.
  defp site_mode do
    cond do
      not Pointing.site_set?() -> {"No location", "the sky and Go To assume 0°, 0°. Set it on Location"}
      Application.get_env(:controller, :site) != nil and is_map(Settings.get("site")) -> {"Location override", "lat/lon set by hand or phone"}
      true -> nil
    end
  end

  # Lock On drives both motors from the camera: say so everywhere, in its own words
  defp lock_on_mode do
    case Controller.LockOn.status() do
      %{state: :off} -> nil
      %{state: st, why: why} -> {"Lock On: #{lock_on_words(st)}", "#{why} · Controls › Lock On"}
      _ -> nil
    end
  end

  defp lock_on_words(:calibrating), do: "calibrating"
  defp lock_on_words(:holding), do: "holding"
  defp lock_on_words(:coasting), do: "target hidden"
  defp lock_on_words(:lost), do: "target lost"
  defp lock_on_words(:waiting), do: "waiting for pictures"
  defp lock_on_words(:stepped_aside), do: "pad in use"
  defp lock_on_words(:resuming), do: "picking up"
  defp lock_on_words(other), do: to_string(other)

  # the optical axis scan drives the mount by itself for a few minutes: say so everywhere
  defp axis_scan_mode do
    case Controller.Optical.AxisScan.status() do
      %{running: true, id: id} -> {"Axis scan running", "#{id} is being moved by the camera scan · Alignment › Optical Axes"}
      _ -> nil
    end
  catch
    :exit, _ -> nil
  end

  # The mount as it stands vs. the ideal: a latitude knob that isn't the site
  # latitude, or a polar axis not on true north, shifts everything the orb and
  # the pointing model draw. Say so.
  defp mount_tilt_mode do
    lat = Pointing.site().lat

    case Settings.get("mount_tilt_deg") do
      t when is_number(t) and abs(t - lat) > 0.5 -> {"Mount tilt #{fmt(t * 1.0)}°", "site latitude is #{fmt(lat * 1.0)}°"}
      _ -> nil
    end
  end

  defp mount_heading_mode do
    case Settings.get("mount_heading_deg") do
      h when is_number(h) and abs(h) > 0.5 -> {"Polar axis #{fmt(abs(h) * 1.0)}° #{if h > 0, do: "E", else: "W"} of true north", "e.g. aligned to a compass"}
      _ -> nil
    end
  end

  # A star alignment replaces the first-order model entirely: every goto and readout
  # goes through the fitted geometry.
  defp lineup_mode do
    case Settings.get("lineup", %{}) do
      map when map_size(map) > 0 ->
        {id, _} = Enum.at(map, 0)
        st = Controller.Sky.Lineup.status(id)

        if st.solved?,
          do: {"Star-aligned · #{st.n} star#{if st.n == 1, do: "", else: "s"}", "#{agree(st.rms_arcmin)}#{st.axis_words}"},
          else: nil

      _ ->
        nil
    end
  end

  # While a new set of points is being fitted the old model is still in force and there is no
  # margin yet (`Lineup.replace/3`). Every open page asks for the modes at that moment, because
  # the points just changed: it must get them, not crash on a number that isn't there.
  defp agree(rms) when is_number(rms), do: "agree to #{:erlang.float_to_binary(rms / 1, decimals: 1)}′ · "
  defp agree(_), do: ""

  # A mount with no home picks its side of the pier for every Go To, and where a hold has to
  # stop, by which side its counterweight is on. Both sides see the same sky, so an alignment
  # only guesses it: until someone looking at the mount says, Go To and tracking wait (#113),
  # and every page says why.
  defp counterweight_mode do
    Settings.get("lineup", %{})
    |> Map.keys()
    |> Enum.find(&match?(%{from: :guessed}, Controller.Sky.Lineup.counterweight(&1)))
    |> case do
      nil -> nil
      id -> {"Counterweight side guessed", "#{id}: Go To and tracking wait until it is told. Tell it on Setup"}
    end
  end

  def clear_sync, do: Settings.put("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})

  def reset_pointing do
    Settings.put("pointing", nil)
    clear_sync()
  end

  defp fmt(x) when x >= 0, do: "+" <> :erlang.float_to_binary(x * 1.0, decimals: 1)
  defp fmt(x), do: :erlang.float_to_binary(x * 1.0, decimals: 1)
end
