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
        do: {"sync offset", "RA #{fmt(off["ra"])}° · Dec #{fmt(off["dec"])}°"}),
      if(p.ha_sign != base.ha_sign, do: {"RA axis flipped", "sign #{p.ha_sign}"}),
      if(p.dec_sign != base.dec_sign, do: {"Dec axis flipped", "sign #{p.dec_sign}"}),
      if(Settings.get("tracking_direction") == "reverse", do: {"tracking reversed", "RA runs the other way"}),
      if(Settings.get("auto_track", true) == false, do: {"auto-track off", "slews won't start tracking"}),
      if(is_map(Settings.get("site")), do: {"site override", "lat/lon set by hand or phone"}),
      mount_tilt_mode(),
      mount_heading_mode()
    ]
    |> Enum.reject(&is_nil/1)
  end

  # The mount as it stands vs. the ideal: a latitude knob that isn't the site
  # latitude, or a polar axis not on true north, shifts everything the orb and
  # the pointing model draw. Say so.
  defp mount_tilt_mode do
    lat = Pointing.site().lat

    case Settings.get("mount_tilt_deg") do
      t when is_number(t) and abs(t - lat) > 0.5 -> {"mount tilt #{fmt(t * 1.0)}°", "site latitude is #{fmt(lat * 1.0)}°"}
      _ -> nil
    end
  end

  defp mount_heading_mode do
    case Settings.get("mount_heading_deg") do
      h when is_number(h) and abs(h) > 0.5 -> {"polar axis #{fmt(abs(h) * 1.0)}° #{if h > 0, do: "E", else: "W"} of true north", "e.g. aligned to a compass"}
      _ -> nil
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
