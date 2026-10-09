defmodule Queues.Meter do
  @moduledoc """
  The last minute of one queue's work, for its numbers: each finished item's
  start and end (monotonic ms), how long it waited first, and its bytes.
  From those: the middle and slow-end (95th percentile) of waiting and of
  working, items and megabytes a second, and how busy the workers were,
  counting the ones still at it.
  """

  @window_ms 60_000

  def new(now \\ now()), do: %{samples: [], since: now}

  def add(meter, start_ms, end_ms, wait_ms, bytes) do
    %{meter | samples: [{start_ms, end_ms, wait_ms, bytes} | meter.samples]} |> prune(end_ms)
  end

  @doc "The numbers, with `running` the start times of work under way and `workers` how many may run at once."
  def read(meter, running \\ [], workers \\ 1, now \\ now()) do
    meter = prune(meter, now)
    from = max(now - @window_ms, meter.since)
    span = max(now - from, 1)
    s = meter.samples
    n = length(s)

    busy =
      Enum.reduce(s, 0, fn {a, b, _, _}, acc -> acc + max(b - max(a, from), 0) end) +
        Enum.reduce(running, 0, fn a, acc -> acc + (now - max(a, from)) end)

    %{
      wait_ms: pct(Enum.map(s, &elem(&1, 2))),
      work_ms: pct(Enum.map(s, fn {a, b, _, _} -> b - a end)),
      per_s: Float.round(n * 1000 / span, 2),
      mb_per_s: Float.round(Enum.reduce(s, 0, &(elem(&1, 3) + &2)) / 1_048_576 * 1000 / span, 2),
      busy: Float.round(min(busy / (span * max(workers, 1)), 1.0), 2),
      window_s: div(span, 1000)
    }
  end

  defp pct([]), do: %{p50: nil, p95: nil}

  defp pct(list) do
    sorted = Enum.sort(list)
    n = length(sorted)
    %{p50: Enum.at(sorted, div(n, 2)), p95: Enum.at(sorted, min(div(n * 95, 100), n - 1))}
  end

  defp prune(meter, now), do: %{meter | samples: Enum.filter(meter.samples, fn {_, b, _, _} -> b >= now - @window_ms end)}

  def now, do: System.monotonic_time(:millisecond)
end
