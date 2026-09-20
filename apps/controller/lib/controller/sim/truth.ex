defmodule Controller.Sim.Truth do
  @moduledoc """
  The simulator's real geometry: where a simulated mount's tube is *actually*
  pointing, as opposed to where the software believes it is.

  A simulated mount that is perfectly aligned teaches nothing. Give it a polar
  axis a few degrees off and a couple of encoder offsets, and Star Align has
  real work to do indoors: the star lands off-centre, you nudge it in, the fit
  converges on these numbers, and afterwards gotos land where they should.

  The truth must never leak into `Controller.Sky.Pointing`, `Lineup` or
  `Tracker`. They work from the encoders and the fitted model alone, or the
  alignment is cheating and proves nothing.
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Model, Pointing}

  @key "sim_truth"

  @doc "True for a simulated mount; only those have a truth."
  def sim?(id) when is_binary(id), do: String.starts_with?(id, "sim")
  def sim?(_), do: false

  @doc "A mount set down badly on purpose: a few degrees off the pole, encoders not quite zeroed."
  def default(lat), do: %{axis_alt: lat / 1 + 2.5, axis_az: 3.0, off_ra: 1.0, off_dec: -1.5}

  @doc "A mount set down perfectly: the software's assumptions are exactly right."
  def ideal(lat), do: Model.ideal(lat / 1)

  @doc "The truth for a mount, atom-keyed, or nil for anything that is not simulated."
  def get(id) do
    if sim?(id) do
      case Settings.get(@key, %{}) |> Map.get(id) do
        %{"axis_alt" => a, "axis_az" => z, "off_ra" => r, "off_dec" => d} ->
          %{axis_alt: a / 1, axis_az: z / 1, off_ra: r / 1, off_dec: d / 1}

        _ ->
          default(Pointing.site().lat)
      end
    end
  end

  @doc "Set a mount's truth."
  def put(id, %{axis_alt: a, axis_az: z, off_ra: r, off_dec: d}) do
    all = Settings.get(@key, %{})
    Settings.put(@key, Map.put(all, id, %{"axis_alt" => a / 1, "axis_az" => z / 1, "off_ra" => r / 1, "off_dec" => d / 1}))
  end

  @doc """
  Where the tube really points, for a simulated mount: the encoders read
  through the truth's geometry. nil when the mount is not simulated or not
  zeroed (before that the encoders mean nothing).
  """
  def radec(%{id: id, homed: true, axes: %{ra: ra, dec: dec}}, now) do
    with true <- sim?(id), %{} = truth <- get(id) do
      site = Pointing.site()
      lst = Astro.lst_deg(now, site.lon)
      Model.radec(truth, Pointing.pointing(), ra.degrees, dec.degrees, site.lat, lst)
    else
      _ -> nil
    end
  end

  def radec(_, _), do: nil

  @doc """
  Where the tube is pointing, for anyone who wants to draw it: the truth for a
  simulated mount, the fitted model's belief for a real one.

  Returns `%{ra_deg, dec_deg, source: :truth | :model}` or nil.
  """
  def looking_at(snap, ctx) when is_map(snap) do
    case radec(snap, ctx.now) do
      {ra, dec} ->
        %{ra_deg: ra, dec_deg: dec, source: :truth}

      nil ->
        case Pointing.scope_radec(snap, ctx) do
          {ra, dec} -> %{ra_deg: ra, dec_deg: dec, source: :model}
          _ -> nil
        end
    end
  end

  def looking_at(_, _), do: nil

  @doc """
  The encoders that would put a simulated mount's tube truly on an RA/Dec: what
  a hand at the eyepiece is aiming for. Used by the eyepiece's own centring and
  by tests that stand in for a person.
  """
  def encoders_for(id, ra_deg, dec_deg, now, near \\ nil) do
    with true <- sim?(id), %{} = truth <- get(id) do
      site = Pointing.site()
      lst = Astro.lst_deg(now, site.lon)
      Model.encoders_radec(truth, Pointing.pointing(), ra_deg, dec_deg, site.lat, lst, near)
    else
      _ -> nil
    end
  end
end
