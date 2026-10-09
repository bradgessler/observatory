defmodule Mount.Transport.Sim do
  @moduledoc """
  A fake EQ6-R motor board that speaks the real wire protocol, so the driver
  runs unchanged with no mount plugged in. Numbers (steps/rev, timer, ratio,
  firmware) are the ones an EQ6-R reports.

  One command no real board has: `Z` with data `1` jams an axis (the motor
  "runs" but the count stays put, as a faulted board would), `0`
  frees it. It is how the driver's stall watch is tested. `Z` with data `2`
  swallows the axis's next goto: its `J` is acknowledged and nothing moves,
  which is what a lost goto looks like from the driver's side.

  It answers at once and stops at once, which the real thing does not. Two
  options make it as slow: `latency_ms:` is how long each frame and its reply
  take (tens of milliseconds on an EQDIR cable at 9600 baud), so the driver
  is busy while it talks, as it is at the telescope; `stop_ms:` is how long
  an axis runs on after `K`, the ramp down, during which the board refuses a
  goto (`!2`) as a real one does.
  """
  @behaviour Mount.Transport

  alias Mount.Protocol, as: P

  @cpr 9_216_000
  @tf 53_694
  @hs 32
  @max_goto_steps_per_s @cpr / 86_164.0905 * 800

  @impl true
  def open(opts) do
    axis = %{
      pos: P.center() * 1.0,
      mode: :slow,
      dir: :forward,
      running: false,
      period: @tf,
      target: nil,
      init: false,
      jammed: false,
      swallow: false,
      stop_at: nil
    }

    {:ok,
     %{
       axes: %{"1" => axis, "2" => axis},
       t: now(),
       latency_ms: Keyword.get(opts, :latency_ms, 0),
       stop_ms: Keyword.get(opts, :stop_ms, 0)
     }}
  end

  @impl true
  def exchange(state, ":" <> frame) do
    frame = String.trim_trailing(frame, "\r")
    if state.latency_ms > 0, do: Process.sleep(state.latency_ms)
    state = advance(state)
    <<cmd::binary-1, axis::binary-1, data::binary>> = frame

    {reply, state} =
      case axis do
        "3" ->
          # Apply to both, report the first axis' reply (as the real board does).
          {r1, s1} = apply_cmd(state, "1", cmd, data)
          {_r2, s2} = apply_cmd(s1, "2", cmd, data)
          {r1, s2}

        a when a in ["1", "2"] ->
          apply_cmd(state, a, cmd, data)

        _ ->
          {"!3", state}
      end

    {:ok, reply <> "\r", state}
  end

  def exchange(state, _), do: {:ok, "!0\r", state}

  @impl true
  def close(_state), do: :ok

  defp apply_cmd(state, a, cmd, data) do
    ax = state.axes[a]

    case {cmd, data} do
      {"e", _} ->
        {"=020B05", state}

      {"a", _} ->
        {"=" <> P.from_int(@cpr), state}

      {"b", _} ->
        {"=" <> P.from_int(@tf), state}

      {"g", _} ->
        {"=20", state}

      {"s", _} ->
        {"=" <> P.from_int(div(@cpr, 180)), state}

      {"j", _} ->
        {"=" <> P.from_int(round(ax.pos) |> rem(0x1000000)), state}

      {"f", _} ->
        {"=" <> status(ax), state}

      {"F", _} ->
        {"=", put(state, a, %{ax | init: true})}

      {"K", _} ->
        if ax.running and state.stop_ms > 0,
          do: {"=", put(state, a, %{ax | stop_at: ax.stop_at || now() + state.stop_ms})},
          else: {"=", put(state, a, %{ax | running: false, target: nil, stop_at: nil})}

      {"L", _} ->
        {"=", put(state, a, %{ax | running: false, target: nil, stop_at: nil})}

      {"Z", v} ->
        {"=", put(state, a, %{ax | jammed: v == "1", swallow: v == "2"})}

      {"G", <<m, d>>} ->
        if ax.running do
          {"!2", state}
        else
          mode =
            case m,
              do: (
                ?0 -> :goto
                ?2 -> :goto
                ?1 -> :slow
                ?3 -> :fast
              )

          dir = if d == ?1, do: :reverse, else: :forward
          {"=", put(state, a, %{ax | mode: mode, dir: dir})}
        end

      {"H", <<_::binary-6>> = v} ->
        {"=", put(state, a, %{ax | target: P.to_int(v)})}

      {"M", <<_::binary-6>>} ->
        {"=", state}

      {"I", <<_::binary-6>> = v} ->
        {"=", put(state, a, %{ax | period: max(P.to_int(v), 1)})}

      {"E", <<_::binary-6>> = v} ->
        {"=", put(state, a, %{ax | pos: P.to_int(v) * 1.0})}

      {"J", _} ->
        cond do
          not ax.init -> {"!4", state}
          ax.mode == :goto and ax.target == nil -> {"!0", state}
          ax.mode == :goto and ax.swallow -> {"=", put(state, a, %{ax | swallow: false, target: nil})}
          true -> {"=", put(state, a, %{ax | running: true})}
        end

      _ ->
        {"!0", state}
    end
  end

  defp put(state, a, ax), do: %{state | axes: Map.put(state.axes, a, ax)}

  defp status(ax) do
    m =
      if(ax.mode == :goto, do: 0, else: 1) + if(ax.dir == :reverse, do: 2, else: 0) +
        if(ax.mode == :fast, do: 4, else: 0)

    r = if(ax.running, do: 1, else: 0)
    i = if(ax.init, do: 1, else: 0)
    Integer.to_string(m, 16) <> Integer.to_string(r, 16) <> Integer.to_string(i, 16)
  end

  defp advance(%{t: t0} = state) do
    t1 = now()
    dt = (t1 - t0) / 1000

    axes =
      Map.new(state.axes, fn {a, ax} -> {a, ax |> step(dt) |> ramped_down(t1)} end)

    %{state | axes: axes, t: t1}
  end

  # a `K` under `stop_ms:` has run its course (or its goto landed first): now the axis is stopped
  defp ramped_down(%{stop_at: at, running: running} = ax, t) when is_integer(at) and (t >= at or not running),
    do: %{ax | running: false, target: nil, stop_at: nil}

  defp ramped_down(ax, _t), do: ax

  defp step(%{running: false} = ax, _dt), do: ax
  defp step(%{jammed: true} = ax, _dt), do: ax

  defp step(%{mode: :goto, target: target} = ax, dt) do
    move = min(@max_goto_steps_per_s * dt, target)
    remaining = target - move
    %{ax | pos: ax.pos + sign(ax) * move, target: remaining, running: remaining > 0}
  end

  defp step(ax, dt) do
    speed = @tf * if(ax.mode == :fast, do: @hs, else: 1) / ax.period
    %{ax | pos: ax.pos + sign(ax) * speed * dt}
  end

  defp sign(%{dir: :forward}), do: 1
  defp sign(%{dir: :reverse}), do: -1

  defp now, do: System.monotonic_time(:millisecond)
end
