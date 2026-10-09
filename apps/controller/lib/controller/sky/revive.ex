defmodule Controller.Sky.Revive do
  @moduledoc """
  The hold picks itself up (#99). A firmware update, a crash, a reboot, or a
  mount cable that drops when a camera is unplugged from the box's USB hub:
  each one ends the hold and stops both axes (the driver does, on every
  connect), and the sky moves on. The hold that was cut off stays in Settings
  (`Controller.Sky.Tracker.interrupted/1`), and a person used to have to tap
  Go To on Home to get it back. A restore that needs a person is a bug.

  This process watches every mount on this machine. When one is connected,
  its hold was cut off, and nothing is holding it now, it goes back to that
  target through the same Go To as every page (`Pointing.slew/5`, tracking
  on), so the hold starts again by itself. Once per cut-off hold: if that Go
  To is refused, the offer stays on Home and this process says why in Events.

  It doesn't guess. It leaves the offer on Home when the way back is longer
  than `max_deg` (10°: forty minutes of sky), when the mount was switched on
  since (its counts restarted, so `interrupted/1` already says nil), and
  when the Go To is refused (a meridian flip, a soft limit, a counterweight
  side never told). It waits up to `clock_wait_ms` (60 s) for network time,
  then goes by the box's own clock, which is seconds behind after a restart:
  arcminutes, inside any eyepiece. A STOP or a person's release clears the
  hold (`Tracker`), so nothing a person ended comes back.

  Started in the app's tree unless `config :controller, revive: false` (the
  tests start their own). Options: `every_ms:` (2000), `max_deg:`,
  `clock_wait_ms:`.
  """
  use GenServer
  require Logger

  alias Controller.Sky.{Astro, Ephemeris, Pointing, Tracker}

  @every_ms 2_000
  @max_deg 10.0
  @clock_wait_ms 60_000

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: Keyword.get(opts, :name, __MODULE__))

  @impl true
  def init(opts) do
    send(self(), :look)

    {:ok,
     %{
       every: Keyword.get(opts, :every_ms, @every_ms),
       max_deg: Keyword.get(opts, :max_deg, @max_deg),
       clock_wait: Keyword.get(opts, :clock_wait_ms, @clock_wait_ms),
       started: System.monotonic_time(:millisecond),
       # the cut-off holds already tried, as {mount, since}: one Go To each
       tried: MapSet.new()
     }}
  end

  @impl true
  def handle_info(:look, s) do
    Process.send_after(self(), :look, s.every)
    ids = safe(fn -> Enum.map(Mount.local_list(), & &1.id) end) || []
    {:noreply, Enum.reduce(ids, s, &look/2)}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp look(id, s) do
    with %{connected: true} = snap <- safe(fn -> Mount.snapshot(id) end),
         %{target: t, since: since} <- safe(fn -> Tracker.interrupted(id) end),
         false <- MapSet.member?(s.tried, {id, since}),
         true <- clock_ok?(s) do
      %{s | tried: MapSet.put(s.tried, {id, since})} |> revive(id, snap, t)
    else
      _ -> s
    end
  end

  defp revive(s, id, snap, t) do
    ctx = Pointing.context(DateTime.utc_now(), id)
    # the Moon and the planets have moved on since
    obj = Enum.find(safe(fn -> Ephemeris.objects(ctx.now, ctx.site) end) || [], &(&1.id == t.id)) || t
    ref = Enum.find(safe(fn -> Mount.list() end) || [], &(&1.id == id))

    away =
      case Pointing.scope_radec(snap, ctx) do
        {ra, dec} -> Astro.separation_radec(ra, dec, obj.ra_deg, obj.dec_deg)
        _ -> nil
      end

    result =
      cond do
        is_nil(ref) -> {:error, :no_mount}
        is_nil(away) -> {:error, :not_lined_up}
        away > s.max_deg -> {:error, {:too_far, away}}
        true -> Pointing.slew(ref, snap, obj, ctx, track: true)
      end

    case result do
      {:ok, _, _} ->
        Tracker.forget_interrupted(id)
        Logger.info("revive: #{id} back on #{obj.name} (#{fmt(away)}° to make up)")
        Telescope.Events.emit(:tracker, :revived, %{id: id, target: obj.name, away_deg: away})

      {:error, why} ->
        Logger.warning("revive: #{id} left #{obj.name} on Home's offer: #{inspect(why)}")
        Telescope.Events.emit(:tracker, :revive_declined, %{id: id, target: obj.name, why: words(why, obj.name)})
    end

    s
  end

  defp clock_ok?(s), do: (safe(fn -> Controller.Clock.synced?() end) == true) or System.monotonic_time(:millisecond) - s.started >= s.clock_wait

  defp words({:too_far, deg}, name), do: "#{name} is #{fmt(deg)}° away by now: too far to go back without someone watching"
  defp words(why, name), do: Pointing.refusal_words(why, name)

  defp fmt(x) when is_number(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp fmt(_), do: "?"

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end
end
