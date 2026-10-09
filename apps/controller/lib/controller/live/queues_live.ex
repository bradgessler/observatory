defmodule Controller.QueuesLive do
  @moduledoc """
  Every step of every pipeline on every machine, and which one is slow.

  One line at the top names the bottleneck (`Queues.bottleneck/1`): the
  step that's busy nearly all the time, or that has work waiting longer and
  longer. Below, machine by machine, each step: how many items wait and for
  how long, how long one takes, how many a second, and how busy it is (a
  bar, and the number). A spool adds the card: what it holds, its budget,
  what's free. Numbers are the last minute's, refreshed every second.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

  @tick_ms 1_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Settings.subscribe()
      Process.send_after(self(), :tick, @tick_ms)
    end

    {:ok, socket |> assign(page_title: "Queues", night: Settings.get("night", false), copying: Controller.Frames.copying?()) |> load()}
  end

  @impl true
  def handle_info(:tick, socket) do
    Process.send_after(self(), :tick, @tick_ms)
    {:noreply, load(socket)}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, "frames_copy", v}, socket), do: {:noreply, assign(socket, copying: v != false)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp load(socket) do
    board = Queues.board()
    slow = Queues.bottleneck(board)
    assign(socket, groups: Enum.chunk_by(board, & &1.node), slow: slow && {slow.node, slow.name}, slow_words: slow_words(slow))
  end

  @impl true
  def handle_event("copying", %{"on" => on}, socket) do
    Controller.Frames.copying(on == "true")
    {:noreply, assign(socket, copying: on == "true")}
  end

  def handle_event("stop", _, socket) do
    for m <- safe_list(), do: safe(fn -> Mount.stop(m) end)
    {:noreply, socket}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="queues" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="System" />
        <.title>Queues</.title>
        <.actions><.help href={~p"/docs/queues"} label="queues" /><.stop /></.actions>
      </:header>

      <p class={["hint", @slow && "tone-caution"]} role="status">{@slow_words}</p>

      <.card :if={Controller.Frames.pull?()} title="Copying From the Boxes">
        <p class="dim" role="status">{if @copying, do: "On: frames come to this machine as the boxes take them.", else: "Paused: frames wait on each box's SD card, and the box's Wi-Fi is left to the phones."}</p>
        <.row>
          <.btn on={!@copying} phx-click="copying" phx-value-on={to_string(!@copying)}>{if @copying, do: "Pause Copying", else: "Resume Copying"}</.btn>
        </.row>
      </.card>

      <.card :for={group <- @groups} title={machine(hd(group).node)}>
        <.items label={"steps on #{machine(hd(group).node)}"}>
          <.item :for={q <- group} as="li" label={label(q, @slow)} detail={detail(q)}>
            <span class="busy" aria-hidden="true"><span style={"width: #{round(q.busy * 100)}%"}></span></span>
            <span class="busy-n">{round(q.busy * 100)}%</span>
          </.item>
        </.items>
      </.card>

      <p :if={@groups == []} class="dim">No queues running yet. Turn on Keep Frames on the Telescope Camera page and they appear here.</p>
    </.page>
    """
  end

  defp slow_words(nil), do: "Keeping up: no step is the bottleneck."

  defp slow_words(q) do
    why =
      cond do
        q.busy >= 0.8 and q.depth > 0 -> "busy #{round(q.busy * 100)}% of the time with #{q.depth} waiting"
        q.busy >= 0.8 -> "busy #{round(q.busy * 100)}% of the time"
        true -> "the oldest has waited #{secs(q.oldest_wait_ms)}"
      end

    "Bottleneck: #{q.label} on #{machine(q.node)}, #{why}."
  end

  defp label(q, slow) do
    if slow == {q.node, q.name}, do: "#{q.label} (bottleneck)", else: q.label
  end

  defp detail(%{kind: :spool} = q) do
    [
      "#{q.depth} waiting#{bytes_in(q.depth_bytes)}",
      q.depth > 0 && "oldest #{secs(q.oldest_wait_ms)}",
      q.running > 0 && "#{q.running} being copied",
      q.per_s > 0 && "#{q.per_s} a second, #{q.mb_per_s} MB/s",
      "SD card #{mb(q.used_bytes)} of #{mb(q.budget_bytes)}" <> if(q.free_bytes, do: ", #{mb(q.free_bytes)} free", else: ""),
      q.counts.taken > 0 && "#{q.counts.taken} copied",
      q.counts.deleted > 0 && "#{q.counts.deleted} deleted for room",
      q.full && "full: new frames are dropped until the Mac catches up"
    ]
    |> join()
  end

  defp detail(q) do
    [
      "#{q.depth} waiting#{bytes_in(q.depth_bytes)}",
      q.depth > 0 && "oldest #{secs(q.oldest_wait_ms)}",
      "#{q.running} of #{q.concurrency} at work",
      q.wait_ms.p50 && "waits #{secs(q.wait_ms.p50)} (slowest #{secs(q.wait_ms.p95)})",
      q.work_ms.p50 && "takes #{secs(q.work_ms.p50)} (slowest #{secs(q.work_ms.p95)})",
      q.per_s > 0 && "#{q.per_s} a second" <> if(q.mb_per_s > 0, do: ", #{q.mb_per_s} MB/s", else: ""),
      q[:parts] && "of which " <> Enum.map_join(q.parts, ", ", fn {k, ms} -> "#{k} #{secs(ms)}" end),
      "#{q.counts.done} done",
      q.counts.failed > 0 && "#{q.counts.failed} failed: #{q.last_error}",
      q.counts.rejected + q.counts.dropped > 0 && "#{q.counts.rejected + q.counts.dropped} dropped for room",
      q.paused && "paused"
    ]
    |> join()
  end

  defp join(parts), do: parts |> Enum.filter(&is_binary/1) |> Enum.join(" · ")

  defp bytes_in(0), do: ""
  defp bytes_in(b), do: " (#{mb(b)})"

  defp mb(nil), do: "?"
  defp mb(b) when b >= 1024 * 1024 * 1024, do: "#{Float.round(b / 1_073_741_824, 1)} GB"
  defp mb(b), do: "#{Float.round(b / 1_048_576, 1)} MB"

  defp secs(nil), do: "?"
  defp secs(ms) when ms < 1_000, do: "#{ms} ms"
  defp secs(ms) when ms < 60_000, do: "#{Float.round(ms / 1000, 1)} s"
  defp secs(ms), do: "#{div(ms, 60_000)} min #{rem(div(ms, 1000), 60)} s"

  # "telescope@observatory.local" is the box called observatory; this machine is this machine
  defp machine(node) when node == node(), do: "This machine"

  defp machine(node) do
    case String.split(to_string(node), "@") do
      [_, host] -> host |> String.replace_suffix(".local", "")
      _ -> to_string(node)
    end
  end

  defp safe_list do
    Mount.list()
  catch
    :exit, _ -> []
  end

  defp safe(fun) do
    fun.()
  catch
    :exit, _ -> nil
  end
end
