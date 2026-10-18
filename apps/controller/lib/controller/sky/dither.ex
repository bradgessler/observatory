defmodule Controller.Sky.Dither do
  @moduledoc """
  Moving the telescope a little between pictures of a run, so that dust on the sensor, hot pixels
  and the sensor's fixed pattern fall on different sky in each picture and stacking (which lines
  the pictures up on their stars) averages them away.

  17 October 2026: the same dark blotches, 30 to 70 arcseconds across and 5 to 10 percent deep,
  sat in exactly the same place in an hour of the Dumbbell Nebula and an hour of the Triangulum
  Galaxy. Held perfectly still, a run stacks its dust right back in. The moves have to be bigger
  than the biggest blotch, so `radius_arcmin` comes from measuring them.

  The offsets are deterministic, never random: a sunflower (Vogel) spiral that fills a disc of
  `radius_arcmin` in `n` steps, each step a golden angle round from the last, so no two pictures
  of a run land on the same spot and any picture's offset can be worked out again from its
  number (`offset/3`). Each picture's sidecar records the offset it was taken at.

  A move is a nudge the way centring nudges (`Controller.Sky.Centre`): the hold is handed the new
  aim and the mount goes there, staying on the side of the pier it is on, then the hold settles.
  Every wait is bounded; a move that would be more than a degree is refused.

      Dither.offset(0, 1.5)                        # {east_arcmin, north_arcmin}
      Dither.step("ttyUSB0", base_aim, {0.4, -0.9}) # :ok | {:error, why}
  """
  alias Controller.Sky.{Astro, Pointing, Tracker}

  @golden_deg 137.50776405003785
  @steps 24
  # the hold is settled when its error has been under this for `@steady_polls` looks in a row
  @steady_arcmin 0.15
  @steady_polls 3
  @poll_ms 500
  @settle_ms 30_000
  @max_move_deg 1.0

  @doc """
  The `k`th offset of a run as `{east_arcmin, north_arcmin}`: a disc of `radius` filled in `n`
  steps (24), then round again.
  """
  def offset(k, radius, n \\ @steps) when is_integer(k) and k >= 0 do
    i = rem(k, n)
    r = radius * :math.sqrt((i + 0.5) / n)
    a = i * @golden_deg * :math.pi() / 180
    {r * :math.sin(a), r * :math.cos(a)}
  end

  @doc "The aim `{east, north}` arcminutes from `base` (a map with `ra_deg`, `dec_deg`)."
  def aim(base, {east, north}) do
    cos_dec = max(:math.cos(base.dec_deg * :math.pi() / 180), 0.05)
    ra = base.ra_deg + east / 60 / cos_dec
    %{base | ra_deg: ra - 360 * Float.floor(ra / 360), dec_deg: base.dec_deg + north / 60}
  end

  @doc """
  Move the hold on mount `id` to `offset` from `base` and wait for it to settle. `base` is the
  aim the run started from (the hold's `aim` in `Tracker.status/1`), so the offsets stay round the
  middle and never walk. `:ok`, or `{:error, why}` with the mount left holding where it got to.
  """
  def step(id, base, offset, opts \\ []) do
    aim = aim(base, offset)

    with %{target: target} <- Tracker.status(id) || {:error, :no_hold},
         %{id: _} = ref <- Enum.find(safe(fn -> Mount.list() end) || [], &(&1.id == id)) || {:error, :no_mount},
         :ok <- move(id, ref, aim, target) do
      settle(id, System.monotonic_time(:millisecond) + Keyword.get(opts, :settle_ms, @settle_ms), 0)
    end
  end

  defp move(id, ref, aim, target) do
    ctx = Pointing.context(DateTime.utc_now(), id)
    snap = Mount.snapshot(id)
    cur = {snap.axes.ra.degrees, snap.axes.dec.degrees}

    case Pointing.axes_for(aim, ctx, near: {:stay, cur}) do
      {ra_a, dec_a} ->
        d_ra = Astro.norm180(ra_a - elem(cur, 0))
        d_dec = Astro.norm180(dec_a - elem(cur, 1))

        if abs(d_ra) > @max_move_deg or abs(d_dec) > @max_move_deg do
          {:error, {:too_far, d_ra, d_dec}}
        else
          # the hold first, holding the target's name: it treats the moves below as its own and
          # keeps the new aim when they land (as centring's nudge does)
          Tracker.track(id, aim, target)
          safe(fn -> if abs(d_ra) > 1.0e-4, do: Mount.goto_relative(ref, :ra, d_ra) end)
          safe(fn -> if abs(d_dec) > 1.0e-4, do: Mount.goto_relative(ref, :dec, d_dec) end)
          :ok
        end

      _ ->
        {:error, :no_alignment}
    end
  end

  defp settle(id, deadline, ok) do
    Process.sleep(@poll_ms)
    t = Tracker.status(id)
    good = is_map(t) and t.paused == false and is_number(t.error_arcmin) and t.error_arcmin < @steady_arcmin
    ok = if good, do: ok + 1, else: 0

    cond do
      ok >= @steady_polls -> :ok
      t == nil -> {:error, :hold_ended}
      System.monotonic_time(:millisecond) > deadline -> {:error, :not_settled}
      true -> settle(id, deadline, ok)
    end
  end

  defp safe(fun) do
    fun.()
  catch
    :exit, _ -> nil
  end
end
