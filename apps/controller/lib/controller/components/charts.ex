defmodule Controller.Components.Charts do
  @moduledoc """
  Small graphics drawn from numbers, server-side, as SVG: no JavaScript, no
  library, re-drawn with the page each time LiveView sends it new numbers.

  The rules are Tufte's: as much of the ink as possible is data; no axes,
  gridlines, legends or boxes where the numbers can be said in words beside
  the line; small multiples share one time axis so rows can be read against
  each other; the newest value is marked where the eye ends up (the right
  end) and said in words next to it, not on a scale. Colour comes from the
  theme (`currentColor` and the tokens), so night mode turns it red with
  everything else.

      <.sparkline values={rates} label="pictures a second, last 5 minutes" />
      <.sparkline values={depths} max={16} area={false} label="waiting" />
      <.fraction value={0.72} label="busy" />

  Every graphic is `role="img"` with an `aria-label`: what it shows, and the
  numbers that matter (now, the range), for a screen reader.
  """
  use Phoenix.Component

  @doc """
  A line of values over time, oldest on the left. nil values are gaps (the
  step wasn't heard from). The scale runs from `min` (0, so a rate's
  baseline is zero, not the smallest value) to `max` (the largest value, or
  given, to share a scale across rows). `area` shades under the line;
  `points` sets how many slots the width holds, so lines with fewer values
  so far start at the right place on a shared time axis.
  """
  attr :values, :list, required: true
  attr :label, :string, required: true
  attr :min, :any, default: 0
  attr :max, :any, default: nil
  attr :points, :integer, default: nil
  attr :area, :boolean, default: true
  attr :width, :integer, default: 160
  attr :height, :integer, default: 28
  attr :class, :any, default: nil
  attr :mark_max, :boolean, default: false, doc: "ring the highest point (a focus curve's peak)"
  attr :bands, :list, default: [], doc: "runs of slots to shade behind the line, `[{first, last}]` (when the telescope was moving)"

  def sparkline(assigns) do
    values = assigns.values
    slots = max(assigns.points || length(values), 2)
    nums = Enum.filter(values, &is_number/1)
    lo = assigns.min || Enum.min(nums, fn -> 0 end)
    hi = assigns.max || Enum.max(nums, fn -> 1 end)
    hi = if hi <= lo, do: lo + 1, else: hi
    {w, h, pad} = {assigns.width, assigns.height, 2}
    offset = slots - length(values)

    xy = fn i, v ->
      x = pad + (i + offset) * (w - 2 * pad) / (slots - 1)
      y = h - pad - (min(max(v, lo), hi) - lo) / (hi - lo) * (h - 2 * pad)
      {Float.round(x * 1.0, 2), Float.round(y * 1.0, 2)}
    end

    # runs of numbers between gaps, each its own line
    runs =
      values
      |> Enum.with_index()
      |> Enum.chunk_by(fn {v, _} -> is_number(v) end)
      |> Enum.filter(fn [{v, _} | _] -> is_number(v) end)
      |> Enum.map(fn run -> Enum.map(run, fn {v, i} -> xy.(i, v) end) end)

    last =
      case values |> Enum.with_index() |> Enum.reverse() |> Enum.find(fn {v, _} -> is_number(v) end) do
        {v, i} -> xy.(i, v)
        nil -> nil
      end

    base = h - pad

    peak =
      if assigns.mark_max do
        case values |> Enum.with_index() |> Enum.filter(fn {v, _} -> is_number(v) end) |> Enum.max_by(fn {v, _} -> v end, fn -> nil end) do
          {v, i} -> xy.(i, v)
          nil -> nil
        end
      end

    slot_w = (w - 2 * pad) / (slots - 1)

    bands =
      for {a, b} <- assigns.bands do
        x0 = pad + (a + offset) * slot_w - slot_w / 2
        x1 = pad + (b + offset) * slot_w + slot_w / 2
        {Float.round(max(x0, 0) * 1.0, 2), Float.round((min(x1, w) - max(x0, 0)) * 1.0, 2)}
      end

    assigns =
      assign(assigns,
        bands: bands,
        lines: Enum.map(runs, &points/1),
        areas: if(assigns.area, do: Enum.map(runs, &area(&1, base)), else: []),
        last: last,
        peak: peak,
        aria: aria(assigns.label, nums)
      )

    ~H"""
    <svg class={["spark", @class]} viewBox={"0 0 #{@width} #{@height}"} width={@width} height={@height} role="img" aria-label={@aria} preserveAspectRatio="none">
      <rect :for={{x, bw} <- @bands} x={x} y="0" width={bw} height={@height} class="spark-band" />
      <polygon :for={a <- @areas} points={a} class="spark-area" />
      <polyline :for={l <- @lines} points={l} class="spark-line" vector-effect="non-scaling-stroke" />
      <circle :if={@peak} cx={elem(@peak, 0)} cy={elem(@peak, 1)} r="3" class="spark-peak" />
      <circle :if={@last} cx={elem(@last, 0)} cy={elem(@last, 1)} r="2" class="spark-end" />
    </svg>
    """
  end

  defp points(run), do: Enum.map_join(run, " ", fn {x, y} -> "#{x},#{y}" end)

  defp area([{x0, _} | _] = run, base) do
    {xn, _} = List.last(run)
    "#{x0},#{base} " <> points(run) <> " #{xn},#{base}"
  end

  defp aria(label, []), do: "#{label}: nothing yet"

  defp aria(label, nums) do
    "#{label}: now #{num(List.last(nums))}, from #{num(Enum.min(nums))} to #{num(Enum.max(nums))}"
  end

  defp num(v) when is_float(v), do: :erlang.float_to_binary(v, decimals: if(abs(v) >= 10, do: 0, else: 1))
  defp num(v), do: to_string(v)

  @doc """
  Where a value sits between two named ends: a track labelled at both ends
  in words (Blurry, Sharp), a marker for now, nothing else. `value` from 0
  (the low end) to 1 (the high end); nil leaves the track empty.
  """
  attr :value, :any, required: true
  attr :low, :string, required: true
  attr :high, :string, required: true
  attr :label, :string, required: true
  attr :class, :any, default: nil

  def gauge(assigns) do
    v = if is_number(assigns.value), do: min(max(assigns.value, 0.0), 1.0)
    assigns = assign(assigns, x: v && Float.round(4 + v * 292, 1), pct: v && round(v * 100))

    ~H"""
    <div class={["gauge", @class]} role="img" aria-label={if @pct, do: "#{@label}: #{@pct}% of the way from #{@low} to #{@high}", else: "#{@label}: nothing yet"}>
      <span class="gauge-end">{@low}</span>
      <svg viewBox="0 0 300 20" preserveAspectRatio="none" aria-hidden="true">
        <rect x="0" y="8" width="300" height="4" rx="2" class="gauge-track" />
        <rect :if={@x} x="0" y="8" width={@x} height="4" rx="2" class="gauge-fill" />
        <rect :if={@x} x={@x - 2} y="2" width="4" height="16" rx="2" class="gauge-mark" />
      </svg>
      <span class="gauge-end">{@high}</span>
    </div>
    """
  end

  @doc "A share from 0 to 1 as a short filled bar on a faint track (busy, full)."
  attr :value, :any, required: true
  attr :label, :string, required: true
  attr :width, :integer, default: 48
  attr :height, :integer, default: 6
  attr :class, :any, default: nil

  def fraction(assigns) do
    v = if is_number(assigns.value), do: min(max(assigns.value, 0.0), 1.0), else: 0.0
    assigns = assign(assigns, fill: Float.round(v * assigns.width, 2), pct: round(v * 100))

    ~H"""
    <svg class={["fraction", @class]} viewBox={"0 0 #{@width} #{@height}"} width={@width} height={@height} role="img" aria-label={"#{@label}: #{@pct}%"}>
      <rect x="0" y="0" width={@width} height={@height} rx={@height / 2} class="fraction-track" />
      <rect x="0" y="0" width={@fill} height={@height} rx={@height / 2} class="fraction-fill" />
    </svg>
    """
  end
end
