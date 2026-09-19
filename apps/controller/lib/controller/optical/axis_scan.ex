defmodule Controller.Optical.AxisScan do
  @moduledoc """
  Find the mount's axes in the camera picture by moving them.

  The procedure, per axis: take a still, turn the axis a small known amount,
  take another, turn back. Block-match the two stills for what moved and fit
  a rotation centre to the flow. The result is drawn over the "before"
  frame: arrows where things moved, a mark where the axis appears to pivot,
  and honest words about how well a pivot explains the motion.

  Runs on demand only, one at a time, as a supervised task; progress and the
  result are broadcast on `"optical"` and kept in Settings under
  `optical_axes` per mount. Moves are ±3° — nothing a cable minds.
  """
  use GenServer
  require Logger

  alias Controller.Optical.{Flow, Frame, Pivot}
  alias Controller.Settings

  # 3° moves the tube end ~15 px at 1920 wide: enough to measure, nothing a cable minds
  @delta_deg 3.0
  # grey frames at a third of the size: 640×360 from a 1080p still
  @factor 3
  @settle_ms 1_500
  @topic "optical"

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Start a scan of both axes on mount `id`. `{:error, :busy}` if one is running."
  def run(id, opts \\ []), do: GenServer.call(__MODULE__, {:run, id, opts})

  def status, do: GenServer.call(__MODULE__, :status)
  def subscribe, do: Telescope.subscribe(@topic)

  @doc "The last result for a mount, or nil."
  def result(id), do: Settings.get("optical_axes", %{}) |> Map.get(id)

  def clear(id), do: Settings.put("optical_axes", Map.delete(Settings.get("optical_axes", %{}), id))

  @impl true
  def init(_) do
    Process.flag(:trap_exit, true)
    {:ok, %{task: nil, id: nil, step: nil, error: nil}}
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, Map.take(s, [:id, :step, :error]) |> Map.put(:running, s.task != nil), s}

  def handle_call({:run, _id, _}, _from, %{task: t} = s) when t != nil, do: {:reply, {:error, :busy}, s}

  def handle_call({:run, id, opts}, _from, s) do
    case Enum.find(Mount.list(), &(&1.id == id)) do
      nil ->
        {:reply, {:error, :no_mount}, s}

      ref ->
        parent = self()
        task = Task.async(fn -> scan(parent, ref, id, opts) end)
        {:reply, :ok, announce(%{s | task: task, id: id, step: :starting, error: nil})}
    end
  end

  @impl true
  def handle_info({:step, step}, s), do: {:noreply, announce(%{s | step: step})}

  def handle_info({ref, result}, %{task: %{ref: ref}} = s) do
    Process.demonitor(ref, [:flush])

    s =
      case result do
        {:ok, res} ->
          Telescope.Events.emit(:optical, :axes_found, %{id: s.id, ra: summary(res.ra), dec: summary(res.dec)})
          Settings.put("optical_axes", Map.put(Settings.get("optical_axes", %{}), s.id, stringify(res)))
          %{s | task: nil, step: :done}

        {:error, why} ->
          Logger.warning("optical: scan failed: #{inspect(why)}")
          %{s | task: nil, step: :failed, error: to_string(why)}
      end

    {:noreply, announce(s)}
  end

  def handle_info({:DOWN, _ref, :process, _pid, reason}, s) do
    {:noreply, announce(%{s | task: nil, step: :failed, error: "scan crashed: #{inspect(reason)}"})}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- the procedure, in the task ------------------------------------------------------

  defp scan(parent, ref, _id, opts) do
    delta = opts[:delta_deg] || @delta_deg
    Telescope.Events.tag("axis scan")

    with :ok <- camera_ready(),
         {:ok, before, before_name, _} <- capture(parent, :capture_before),
         {:ok, ra} <- axis(parent, ref, :ra, delta, before),
         {:ok, dec} <- axis(parent, ref, :dec, delta, before) do
      {:ok, %{"at" => DateTime.to_iso8601(DateTime.utc_now()), "frame" => before_name, "delta_deg" => delta, "scale" => before.scale, "w" => before.w, "h" => before.h, ra: ra, dec: dec}}
    end
  end

  defp camera_ready do
    case Watch.status() do
      %{tool: nil} -> {:error, "no camera tool on this machine"}
      _ -> :ok
    end
  end

  defp capture(parent, step, after_at \\ nil, tries \\ 0) do
    send(parent, {:step, step})

    case Watch.capture() do
      %{at: at} ->
        cond do
          # while video runs, stills come from the encoder every few seconds:
          # make sure this one was taken after the move, not before it
          after_at && DateTime.compare(at, after_at) != :gt && tries < 12 ->
            Process.sleep(1_000)
            capture(parent, step, after_at, tries + 1)

          after_at && DateTime.compare(at, after_at) != :gt ->
            {:error, "camera gave no new frame"}

          true ->
            case Watch.latest() do
              %{jpeg: jpeg} ->
                name = Watch.history(limit: 1) |> List.first() |> then(&(&1 && &1.name))
                with {:ok, frame} <- Frame.from_binary(jpeg, @factor), do: {:ok, frame, name, at}

              _ ->
                {:error, "no frame"}
            end
        end

      {:error, why} ->
        {:error, "capture failed: #{why}"}
    end
  end

  defp axis(parent, ref, axis, delta, before) do
    send(parent, {:step, {:move, axis}})

    moved_at = DateTime.utc_now()

    with :ok <- Mount.goto_relative(ref, axis, delta),
         :ok <- settle(ref, axis),
         {:ok, after_frame, after_name, _} <- capture(parent, {:capture, axis}, moved_at),
         :ok <- Mount.goto_relative(ref, axis, -delta),
         :ok <- settle(ref, axis) do
      send(parent, {:step, {:analyse, axis}})
      raw = Flow.between(before, after_frame, search: 8)
      vectors = Pivot.coherent(raw)
      fit = Pivot.fit(vectors)
      {:ok, %{vectors: vectors, dropped: length(raw) - length(vectors), fit: fit, line: Pivot.axis_line(vectors), frame_after: after_name, words: Pivot.words(fit)}}
    else
      {:error, :limit} -> {:error, "#{axis}: soft limit — move the mount away from a limit and try again"}
      {:error, e} -> {:error, "#{axis}: #{inspect(e)}"}
    end
  end

  # wait for the goto to land, then a beat for the tube to stop swaying
  defp settle(ref, axis, waited \\ 0) do
    Process.sleep(250)

    case Mount.snapshot(ref) do
      %{axes: axes} ->
        cond do
          axes[axis].running and waited < 30_000 -> settle(ref, axis, waited + 250)
          axes[axis].running -> {:error, "#{axis} still moving after 30 s"}
          true -> Process.sleep(@settle_ms); :ok
        end

      _ ->
        {:error, "no snapshot"}
    end
  end

  defp summary(%{fit: nil}), do: "no motion seen"
  defp summary(%{fit: f}), do: "#{f.n} blocks · quality #{Float.round(f.quality, 2)} · coherence #{Float.round(f.coherence, 2)}"

  # settings are JSON: atoms → strings, tuples → lists
  defp stringify(%{ra: ra, dec: dec} = res) do
    res
    |> Map.delete(:ra)
    |> Map.delete(:dec)
    |> Map.put("ra", axis_json(ra))
    |> Map.put("dec", axis_json(dec))
  end

  defp axis_json(%{vectors: vs, fit: fit, line: line, dropped: dropped, frame_after: fa, words: words}) do
    %{
      "vectors" => Enum.map(vs, &%{"x" => &1.x, "y" => &1.y, "dx" => &1.dx, "dy" => &1.dy}),
      "dropped" => dropped,
      "line" => line && Map.new(line, fn {k, v} -> {Atom.to_string(k), v} end),
      "fit" => fit && Map.new(fit, fn {k, v} -> {Atom.to_string(k), v} end),
      "frame_after" => fa,
      "words" => words
    }
  end

  defp announce(s) do
    Telescope.broadcast(@topic, {:optical, Map.take(s, [:id, :step, :error]) |> Map.put(:running, s.task != nil)})
    s
  end
end
