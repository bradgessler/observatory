defmodule Controller.Sky.Daylight do
  @moduledoc """
  How dark the sky is, by where the Sun is: the five phases an observer
  plans by, in their standard names. Daylight (the Sun up), civil twilight
  (down to 6° below: bright), nautical twilight (to 12°: the bright stars
  out), astronomical twilight (to 18°: faint things still washed out), and
  dark. The Sky toolbar's solar graph, the sky charts' ground and an
  object's night all take their words and their limits from here.
  """

  alias Controller.Sky.Ephemeris

  @phases [
    {:day, "Daylight", 0.0},
    {:civil, "Civil twilight", -6.0},
    {:nautical, "Nautical twilight", -12.0},
    {:astronomical, "Astronomical twilight", -18.0},
    {:dark, "Dark", -90.0}
  ]

  @doc "The phase for the Sun's altitude (degrees): `{key, name}`."
  def phase(sun_alt) do
    {key, name, _} = Enum.find(@phases, fn {_, _, above} -> sun_alt > above end) || List.last(@phases)
    {key, name}
  end

  @doc "The Sun's altitude at `at` from `site`, degrees."
  def sun_alt(at, site), do: Ephemeris.sun_alt(at, site)

  @doc "The phases in order, `[{key, name, lower_limit_deg}]`: for a legend or the graph's bands."
  def phases, do: @phases

  @doc """
  The Sun's altitude over the day and night around `at`: from the local noon
  before it to the noon after (so the night sits in the middle, whole), as
  `[{minutes_from_start, alt}]` every `step` minutes, with that start.
  """
  def day(at, site, utc_offset_min, step \\ 20) do
    off = (utc_offset_min || 0) * 60
    local = DateTime.add(at, off, :second)
    since_noon = rem(local.hour * 60 + local.minute - 12 * 60 + 24 * 60, 24 * 60)
    start = at |> DateTime.add(-since_noon * 60, :second) |> DateTime.truncate(:second) |> Map.put(:second, 0)
    samples = for m <- 0..(24 * 60)//step, do: {m, sun_alt(DateTime.add(start, m * 60, :second), site)}
    {start, samples}
  end

  @doc """
  When the phase at `at` next changes, within a day: `{time, {key, name}}`
  of the phase it changes to, or nil (the midnight Sun, the polar night).
  """
  def next_change(at, site) do
    {now, _} = phase(sun_alt(at, site))

    Enum.find_value(1..(24 * 12), fn i ->
      t = DateTime.add(at, i * 300, :second)
      {key, _} = p = phase(sun_alt(t, site))
      if key != now, do: {t, p}
    end)
  end
end
