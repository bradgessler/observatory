defmodule Controller.Clock do
  @moduledoc """
  This machine's clock: whether the network set it, and setting it from a
  phone when it did not.

  A box in a field has no internet time and no real-time clock, so after a
  power cut its clock starts from wherever it was last saved and drifts. A
  phone's clock is set by its carrier. So a box (`config :controller,
  clock_from_browser: true`) takes the time from the first phone that opens
  the Site page, when its own clock is not network-set and the two disagree
  by more than 2 s. A Mac's clock is never touched.
  """
  require Logger

  @compile {:no_warn_undefined, [NervesTime, NervesTime.SystemTime]}

  @doc "Was this clock set by the network? A Mac keeps its own time: yes."
  def synced? do
    # `config :controller, :clock_synced` stands in for the network's answer (tests of what an unset clock does)
    case Application.get_env(:controller, :clock_synced) do
      nil -> if Code.ensure_loaded?(NervesTime), do: NervesTime.synchronized?(), else: true
      said -> said
    end
  catch
    _, _ -> false
  end

  @doc "May a phone set this clock? Only on a box that says so."
  def settable?, do: Application.get_env(:controller, :clock_from_browser, false) and Code.ensure_loaded?(NervesTime.SystemTime)

  @doc "Set the clock to `utc`, and record that it happened."
  def set(%DateTime{} = utc) do
    before = DateTime.utc_now()

    case NervesTime.SystemTime.set_time(DateTime.to_naive(utc)) do
      :ok ->
        Logger.info("Clock set from a phone: #{DateTime.to_iso8601(before)} -> #{DateTime.to_iso8601(utc)}")
        Telescope.Events.emit(:system, :clock_set, %{from: DateTime.to_iso8601(before), to: DateTime.to_iso8601(utc)})
        :ok

      other ->
        other
    end
  end
end
