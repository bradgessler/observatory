defmodule Mount.Transport.Sim do
  @moduledoc """
  A fake EQ6-R motor board that speaks the real wire protocol, so the driver
  runs unchanged with no mount plugged in. Numbers (steps/rev, timer, ratio,
  firmware) are the ones an EQ6-R reports.

  One command no real board has: `Z` with data `1` jams an axis (the motor
  "runs" but the count stays put, as a faulted board would), `0`
  frees it. It is how the driver's stall watch is tested.
  """
  @behaviour Mount.Transport

  alias Mount.Protocol, as: P

  @cpr 9_216_000
  @tf 53_694
  @hs 32
  @max_goto_steps_per_s @cpr / 86_164.0905 * 800

  @impl true
  def open(_opts) do
    axis = %{
      pos: P.center() * 1.0,
      mode: :slow,
      dir: :forward,
      running: false,
      period: @tf,
      target: nil,
      init: false,
      jammed: false
    }

    {:ok, %{axes: %{"1" => axis, "2" => axis}, t: now()}}
  end

  @impl true
  def exchange(state, ":" <> frame) do
    frame = String.trim_trailing(frame, "\r")
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
        {"=", put(state, a, %{ax | running: false, target: nil})}

      {"L", _} ->
        {"=", put(state, a, %{ax | running: false, target: nil})}

      {"Z", v} ->
        {"=", put(state, a, %{ax | jammed: v == "1"})}

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
      Map.new(state.axes, fn {a, ax} -> {a, step(ax, dt)} end)

    %{state | axes: axes, t: t1}
  end

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
