defmodule Controller.Sky.Reach do
  @moduledoc """
  Three questions a person has about a target before touching anything, each
  answered with the one thing to do when the answer is no:

    * **Look**: is it up, and clear of the trees? If not, when?
    * **Go To**: will a Go To put it in the eyepiece from here? An alignment,
      the margin against the field, and whether it has to flip the mount.
    * **Track**: once there, how long does tracking keep it? Until it sets,
      goes behind the trees, or the counterweight reaches its limit (a mount
      whose home was never set has no soft limits: the counterweight is the
      limit, and the next Go To flips).

  On a mount whose home was never set, with the counterweight's side only
  guessed, Go To and tracking both wait for that one answer
  (`Pointing.side_guessed?/2`), and the two answers say so.

  Worked out with the same functions Go To and the hold use (`Pointing.landing/4`,
  `Pointing.counterweight/2`), so a page can't promise what the mount won't do.

  Each answer is `%{tone, mark, text, at}`: `tone` is `:good | :caution | :bad | :off`
  (for colour), `mark` a character that carries the same state without colour,
  `text` one line, `at` the time it changes (or nil), for a page to show in the
  viewer's clock. Words take a `clock` function: `DateTime.t() -> "01:40"`.
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Ephemeris, Pointing}

  @step_min 5
  @horizon_h 12
  # civil twilight over: dark enough to look
  @dark -6.0

  @doc """
  The three answers for `obj` on the mount in `snap` (nil: none), with the
  pointing context `ctx`. Options: `:horizon` (tree line map, default the
  saved one), `:trees?` (whether a tree line was given), `:field` (eyepiece
  field, arcmin), `:lock` (`Lineup.status/1`), `:tracker` (`Tracker.status/1`),
  `:ended` (`Tracker.ended/1`), `:clock`.
  """
  def of(obj, snap, ctx, opts \\ []) do
    horizon = Keyword.get_lazy(opts, :horizon, &Settings.horizon/0)
    trees? = Keyword.get_lazy(opts, :trees?, fn -> Settings.get("horizon") != nil end)
    clock = Keyword.get(opts, :clock, &Calendar.strftime(&1, "%H:%M UTC"))
    tree_at = fn az -> if trees?, do: Settings.horizon_at(horizon, az), else: 0 end

    sky = sky(obj, ctx, tree_at)
    go = go(obj, snap, ctx, sky, opts)
    track = track(obj, snap, ctx, sky, go, tree_at, opts)

    %{
      look: look_words(sky, trees?, clock),
      go: go_words(go, obj, opts),
      track: track_words(track, obj, clock)
    }
  end

  # -- look ---------------------------------------------------------------------------

  # where it is now and when that changes, stepping the next twelve hours.
  # At night the window also ends at dawn; in daylight the page says so.
  defp sky(obj, ctx, tree_at) do
    at = fn t ->
      {alt, az} =
        Astro.alt_az(obj.ra_deg, obj.dec_deg, ctx.site.lat, Astro.lst_deg(t, ctx.site.lon))

      %{alt: alt, az: az, tree: tree_at.(az), dark: Ephemeris.sun_alt(t, ctx.site) < @dark}
    end

    now = at.(ctx.now)
    clear? = fn p -> p.alt > max(p.tree, 0) and (p.dark or not now.dark) end

    steps =
      for m <- @step_min..(@horizon_h * 60)//@step_min,
          t = DateTime.add(ctx.now, m * 60),
          do: {t, at.(t)}

    change = Enum.find(steps, fn {_, p} -> clear?.(p) != clear?.(now) end)
    dark_at = if not now.dark, do: Enum.find_value(steps, fn {t, p} -> p.dark && t end)

    ends =
      case change do
        {_, %{dark: false}} when now.dark -> :dawn
        {_, %{alt: alt}} when alt <= 0 -> :sets
        {_, _} -> :trees
        nil -> nil
      end

    Map.merge(now, %{
      clear: clear?.(now),
      change_at: change && elem(change, 0),
      ends: ends,
      dark_at: dark_at,
      at: at
    })
  end

  defp look_words(%{dark: false, dark_at: %DateTime{} = t}, _trees?, clock),
    do: check(:off, "–", "Daylight now; dark at #{clock.(t)}", t)

  defp look_words(%{clear: true} = s, trees?, clock) do
    where = if trees? and s.tree > 0, do: "clear of the trees", else: "above the horizon"

    until =
      case {s.ends, s.change_at} do
        {_, nil} -> " all night"
        {:dawn, t} -> " until dawn, #{clock.(t)}"
        {:sets, t} -> " until it sets, #{clock.(t)}"
        {_, t} -> " until it goes behind the trees, #{clock.(t)}"
      end

    check(:good, "✓", "#{round(s.alt)}° up, #{where}#{until}", s.change_at)
  end

  defp look_words(%{alt: alt} = s, _trees?, clock) when alt > 0 do
    clear = if s.change_at, do: "; clear at #{clock.(s.change_at)}", else: "; not clear tonight"

    check(
      :caution,
      "–",
      "Behind your trees (#{round(alt)}° up, trees to #{round(s.tree)}°)#{clear}",
      s.change_at
    )
  end

  defp look_words(s, _trees?, clock) do
    up = if s.change_at, do: "; up at #{clock.(s.change_at)}", else: "; not up tonight"
    check(:off, "–", "Below the horizon#{up}", s.change_at)
  end

  # -- go to --------------------------------------------------------------------------

  defp go(obj, snap, ctx, sky, _opts) do
    cond do
      is_nil(snap) or not snap.connected -> :no_mount
      not snap.homed and not Pointing.lined_up?(ctx) -> :no_lock
      Pointing.side_guessed?(snap, ctx) -> :side_unknown
      sky.alt <= 0 -> :down
      snap.homed -> {:zeroed, nil}
      true -> {:model, Pointing.landing(obj, snap, ctx)}
    end
  end

  defp go_words(:no_mount, _obj, _opts), do: check(:off, "–", "No mount connected", nil)

  defp go_words(:no_lock, _obj, _opts),
    do: check(:caution, "×", "Not aligned: center any star or planet and tap Centered", nil)

  # the question, in the words the Counterweight card asks it
  defp go_words(:side_unknown, _obj, _opts),
    do: check(:caution, "×", "Waits for one answer: is the counterweight below or above level right now?", nil)

  defp go_words(:down, _obj, _opts), do: check(:off, "–", "Waits until it's up", nil)

  defp go_words({:zeroed, _}, _obj, _opts),
    do: check(:good, "✓", "Ready: the home position places it", nil)

  defp go_words({:model, plan}, _obj, opts) do
    field = Keyword.get(opts, :field, 72)

    margin =
      case Keyword.get(opts, :lock) do
        %{n: n, rms_arcmin: rms} when n >= 3 and is_number(rms) -> round(2 * rms)
        _ -> nil
      end

    land =
      cond do
        margin == nil -> "lands close; too few points to say how close"
        margin < field / 2 -> "lands within ±#{margin}′, inside your #{field}′ field"
        true -> "lands within ±#{margin}′, wider than your field: Spiral Search finds it"
      end

    cond do
      plan.pose == :flip ->
        check(:caution, "!", "Flips the mount first, in two legs, then #{land}", nil)

      margin != nil and margin < field / 2 ->
        check(:good, "✓", String.capitalize(land), nil)

      true ->
        check(:caution, "!", String.capitalize(land), nil)
    end
  end

  # -- track --------------------------------------------------------------------------

  defp track(obj, snap, ctx, sky, go, tree_at, opts) do
    tracker = Keyword.get(opts, :tracker)
    ended = Keyword.get(opts, :ended)
    holding? = is_map(tracker) and same?(tracker[:target], obj)

    cond do
      go in [:no_mount, :no_lock, :side_unknown] ->
        go

      holding? ->
        {:until,
         hold_end(obj, snap, ctx, {snap.axes.ra.degrees, snap.axes.dec.degrees}, tree_at, sky.dark),
         tracker}

      # (a hold refused for a guessed side: past here the side is told, so that no longer holds)
      match?(%{why: _}, ended) and ended.name == obj[:name] and ended.why != :counterweight_unknown ->
        {:ended, ended}

      not sky.clear ->
        if sky.alt > 0, do: :trees, else: :down

      match?({:zeroed, _}, go) ->
        # the driver's sidereal tracking: until it sets or meets the trees
        stop = sky.change_at && {sky.ends, sky.change_at}

        {:until, stop, nil}

      true ->
        {:model, plan} = go
        {:until, hold_end(obj, snap, ctx, {plan.ra, plan.dec}, tree_at, sky.dark), nil}
    end
  end

  # step the hold forward from its pose: the first thing that ends it
  defp hold_end(obj, snap, ctx, pose, tree_at, dark_now) do
    Enum.reduce_while(1..div(@horizon_h * 60, @step_min), pose, fn i, pose ->
      t = DateTime.add(ctx.now, i * @step_min * 60)
      c = %{ctx | now: t}
      {ra, _} = pose = Pointing.axes_for(obj, c, near: {:stay, pose})

      {alt, az} =
        Astro.alt_az(obj.ra_deg, obj.dec_deg, ctx.site.lat, Astro.lst_deg(t, ctx.site.lon))

      cond do
        # the hold's own rule (`Pointing.hold_limit?/1`)
        not snap.homed and Pointing.hold_limit?(Pointing.counterweight(c, ra)) ->
          {:halt, {:meridian, t}}

        dark_now and Ephemeris.sun_alt(t, ctx.site) >= @dark ->
          {:halt, {:dawn, t}}

        alt <= 0 ->
          {:halt, {:sets, t}}

        alt <= tree_at.(az) ->
          {:halt, {:trees, t}}

        true ->
          {:cont, pose}
      end
    end)
    |> case do
      {_, %DateTime{}} = stop -> stop
      _ -> nil
    end
  end

  defp same?(%{id: id}, %{id: id}) when not is_nil(id), do: true
  defp same?(%{name: n}, %{name: n}), do: true
  defp same?(_, _), do: false

  defp track_words(:no_mount, _obj, _clock), do: check(:off, "–", "No mount connected", nil)

  defp track_words(:no_lock, _obj, _clock),
    do: check(:caution, "×", "Needs an alignment first: tracking steers by it", nil)

  defp track_words(:side_unknown, _obj, _clock),
    do: check(:caution, "×", "Waits for the same answer: on a guess, where tracking has to stop could be upside down", nil)

  defp track_words(:down, _obj, _clock), do: check(:off, "–", "Once it's up", nil)
  defp track_words(:trees, _obj, _clock), do: check(:off, "–", "Once it clears the trees", nil)

  defp track_words({:ended, %{why: why, at: at}}, _obj, clock) do
    because =
      case why do
        :meridian ->
          "the counterweight reached its limit. Go To again flips the mount and tracks it from the other side"

        :estop ->
          "STOP was pressed. Go To again to track it"

        :lost ->
          "it was more than 5° off, so tracking stood down rather than chase. Go To again"

        _ ->
          "the mount went away. Go To again once it's back"
      end

    check(:caution, "!", "Stopped tracking it at #{clock.(at)}: #{because}", nil)
  end

  defp track_words({:until, stop, tracker}, _obj, clock) do
    now = if tracker, do: "Tracking it now#{off(tracker)}. ", else: "Tracks it "

    {tone, mark, rest} =
      case stop do
        nil ->
          {:good, "✓", "all night"}

        {:sets, t} ->
          {:good, "✓", "until it sets at #{clock.(t)}"}

        {:trees, t} ->
          {:good, "✓", "until it goes behind the trees at #{clock.(t)}"}

        {:dawn, t} ->
          {:good, "✓", "until dawn at #{clock.(t)}"}

        {:meridian, t} ->
          {:caution, "!",
           "until #{clock.(t)}, when the counterweight reaches its limit; then Go To flips it"}
      end

    rest = if tracker, do: "Until " <> String.replace_prefix(rest, "until ", ""), else: rest
    rest = if tracker && rest == "Until all night", do: "All night", else: rest
    check(tone, mark, now <> rest, stop && elem(stop, 1))
  end

  defp off(%{error_arcmin: e}) when is_number(e),
    do: ", #{:erlang.float_to_binary(e * 1.0, decimals: 1)}′ off"

  defp off(%{paused: p}) when p in [:hand, :goto], do: ", paused while you drive"
  defp off(_), do: ""

  defp check(tone, mark, text, at), do: %{tone: tone, mark: mark, text: text, at: at}
end
