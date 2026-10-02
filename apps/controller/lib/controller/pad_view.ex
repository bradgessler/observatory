defmodule Controller.PadView do
  @moduledoc """
  The pad's hat moves the view the way the Center page's touchpad does: the
  same map, the same Backwards. Keeps `Input.Mapper` in eyepiece mode with
  the `"view_map"` setting, now, whenever a phone changes it, and every 30 s
  in case the mapper restarted and forgot.
  """
  use GenServer
  require Logger

  alias Controller.Settings

  @every_ms 30_000

  # The view map before anyone sets one: down on the screen is +RA, right is
  # -Dec. Kept here, not in the Center page that edits it: this process runs
  # all the time, and a page's module is swapped out whenever code reloads.
  @view_map %{"down" => ["ra", 1], "right" => ["dec", -1]}

  @doc "The view map before anyone sets one (the Center page's and the pad's)."
  def default_view_map, do: @view_map

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "The pad's settings for a view map (`%{\"down\" => [\"ra\", 1], \"right\" => [\"dec\", -1]}`)."
  def pad_map(%{"down" => [ad, sd], "right" => [ar, sr]}),
    do: %{hat: :eyepiece, view_down: {String.to_existing_atom(ad), sd}, view_right: {String.to_existing_atom(ar), sr}}

  @impl true
  def init(_) do
    Settings.subscribe()
    send(self(), :push)
    {:ok, nil}
  end

  @impl true
  def handle_info(:push, s) do
    push(Settings.get("view_map", @view_map))
    Process.send_after(self(), :push, @every_ms)
    {:noreply, s}
  end

  def handle_info({:settings, "view_map", map}, s) do
    push(map)
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  # no mapper on this node (or not up yet), or a map it can't read: the next
  # push will do. Never a crash: restarted into the same push, a crash would
  # spend the app's restart budget and take every page down with it.
  defp push(map) do
    Input.Mapper.configure(pad_map(map))
  catch
    :exit, _ ->
      :ok

    kind, reason ->
      Logger.warning("pad view: couldn't set the pad's map (#{Exception.format_banner(kind, reason)}); trying again in #{div(@every_ms, 1000)} s")
      :ok
  end
end
