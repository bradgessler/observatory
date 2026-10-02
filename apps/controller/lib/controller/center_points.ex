defmodule Controller.CenterPoints do
  @moduledoc """
  "It's centred", in the field with no one to tell but the pad (#94).

  The pad's Centered button and the Center page's both broadcast
  `{:centered, %{mount, ra, dec, at}}` on `"center"`, with both axes read at
  the press. This turns that into an alignment point on whatever the hold
  is keeping: the target of the last Go To. A planet or the Moon is worked
  out again for the moment of the press (they move against the stars). With
  nothing held there is nothing to name, and it says so rather than guess.

  Says what it did on `"center"`: `{:centered_point, mount, %{name, n, rms_arcmin, at}}`
  or `{:centered_point, mount, {:unknown, at}}`. Pages show it with an Undo.
  """
  use GenServer
  require Logger

  alias Controller.Sky.{Ephemeris, Lineup, Pointing, Tracker}

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_) do
    Telescope.subscribe("center")
    {:ok, %{}}
  end

  @impl true
  def handle_info({:centered, %{mount: id, ra: ra, dec: dec} = data}, s) do
    at = parse_at(data[:at])

    case held(id, at) do
      nil ->
        Telescope.broadcast("center", {:centered_point, id, {:unknown, at}})

      obj ->
        snap = %{id: id, axes: %{ra: %{degrees: ra}, dec: %{degrees: dec}}, homed_at: homed_at(id)}
        st = Lineup.add(snap, obj, at)
        Logger.info("centered point: #{id} on #{obj.name} (#{st.n} points)")
        Telescope.broadcast("center", {:centered_point, id, %{name: obj.name, n: st.n, rms_arcmin: st.rms_arcmin, at: at}})
    end

    {:noreply, s}
  rescue
    e ->
      Logger.error("centered point: #{Exception.message(e)}")
      {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  # what the hold is keeping, as the catalogue has it; a solar-system body
  # where it is at the moment of the press
  defp held(id, at) do
    case Tracker.status(id) do
      %{target: %{name: name, ra_deg: _, dec_deg: _} = t} when is_binary(name) ->
        moving = t[:id] && Enum.find(Ephemeris.objects(at, Pointing.site()), &(&1.id == t[:id]))
        (moving && Map.take(moving, [:id, :name, :ra_deg, :dec_deg])) || t

      _ ->
        nil
    end
  end

  defp homed_at(id) do
    Mount.snapshot(id)[:homed_at]
  catch
    :exit, _ -> nil
  end

  defp parse_at(s) when is_binary(s) do
    case DateTime.from_iso8601(s) do
      {:ok, t, _} -> t
      _ -> DateTime.utc_now()
    end
  end

  defp parse_at(_), do: DateTime.utc_now()
end
