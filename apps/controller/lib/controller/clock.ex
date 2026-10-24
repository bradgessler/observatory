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

  **Straight after a boot** the same box has the same problem for a minute or
  so even with internet: it starts from the time it last saved, and network
  time takes its own time to arrive. On 12 October 2026 a picture taken 40 s
  after a reboot was stamped three and a half minutes slow. So:

    * a box takes the time from another machine of its cluster whose own
      clock is set and is not a box's (`from_peers/0`, `Controller.Clock.Peers`):
      a Mac on the same LAN answers within moments of the box joining it;
    * `set?/0` is the question everything asks before it stamps or moves by
      the time: set by the network, by a peer or by a phone. The stills
      camera waits for it before the next picture of a run, a plate is not
      solved without it, and a hold is not revived without it. Each waits a
      bounded time and then carries on, saying the clock is not set.
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

  @doc """
  Is this clock right, by any of the ways it can be: the network's time, or set this boot from a
  phone or from another machine of the cluster (`set/1`)? What a stamp or a sidereal time should
  wait for.
  """
  def set?, do: synced?() or :persistent_term.get({__MODULE__, :set}, false)

  @doc """
  Take the time from another machine of the cluster, when this clock may be set (`settable?/0`)
  and is not (`set?/0`): the first machine that answers, whose own clock is the network's and is
  not itself a box's settable clock. The answer is corrected by half the round trip, and one
  that took longer than half a second to come is not used. `:ok`, or `:no` when there was
  nobody to ask or nothing to do.
  """
  def from_peers(nodes \\ Node.list()) do
    if settable?() and not set?() do
      Enum.find_value(nodes, :no, fn node ->
        t0 = System.monotonic_time(:millisecond)

        case ask(node) do
          {true, false, %DateTime{} = utc} ->
            rtt = System.monotonic_time(:millisecond) - t0
            if rtt <= 500, do: set(DateTime.add(utc, div(rtt, 2), :millisecond), "the cluster (#{node})") == :ok && :ok

          _ ->
            nil
        end
      end)
    else
      :no
    end
  end

  # another machine's clock: is it the network's, could a phone set it (a box: not to be trusted
  # more than this one), and what it reads
  defp ask(node) do
    :erpc.call(node, __MODULE__, :reading, [], 1_000)
  catch
    _, _ -> nil
  end

  @doc false
  def reading, do: {synced?(), settable?(), DateTime.utc_now()}

  @doc """
  Where this clock's time came from, in one word for a record (`OBS CLOCK SOURCE`): `"network"`
  (network time; a Mac's own clock is that), `"peer"` (another machine of the cluster), `"phone"`,
  or `"own"` (nobody has set it this boot: it may be off by minutes).
  """
  def source do
    cond do
      synced?() -> "network"
      :persistent_term.get({__MODULE__, :set}, false) -> :persistent_term.get({__MODULE__, :set_by}, "phone")
      true -> "own"
    end
  end

  @doc "May a phone set this clock? Only on a box that says so."
  def settable?, do: Application.get_env(:controller, :clock_from_browser, false) and Code.ensure_loaded?(NervesTime.SystemTime)

  @doc "Set the clock to `utc` (said by `from`: a phone, or a machine of the cluster), and record that it happened."
  def set(%DateTime{} = utc, from \\ "a phone") do
    before = DateTime.utc_now()

    case NervesTime.SystemTime.set_time(DateTime.to_naive(utc)) do
      :ok ->
        :persistent_term.put({__MODULE__, :set}, true)
        :persistent_term.put({__MODULE__, :set_by}, if(String.starts_with?(to_string(from), "the cluster"), do: "peer", else: "phone"))
        Logger.info("Clock set from #{from}: #{DateTime.to_iso8601(before)} -> #{DateTime.to_iso8601(utc)}")
        Telescope.Events.emit(:system, :clock_set, %{from: DateTime.to_iso8601(before), to: DateTime.to_iso8601(utc), by: from, off_s: DateTime.diff(utc, before, :second)})
        :ok

      other ->
        other
    end
  end
end

defmodule Controller.Clock.Peers do
  @moduledoc """
  On a box whose clock is not set yet, asks the other machines of its cluster for the time
  (`Controller.Clock.from_peers/0`) every two seconds until the clock is set by anyone, then
  goes quiet (it looks again every minute, for a clock that was never set this boot). On a
  machine that keeps its own time it does nothing.
  """
  use GenServer

  @soon 2_000
  @later 60_000

  def start_link(_), do: GenServer.start_link(__MODULE__, nil, name: __MODULE__)

  @impl true
  def init(_) do
    Process.send_after(self(), :ask, @soon)
    {:ok, nil}
  end

  @impl true
  def handle_info(:ask, s) do
    unset? = safe(fn -> Controller.Clock.settable?() and not Controller.Clock.set?() end) == true
    if unset?, do: safe(fn -> Controller.Clock.from_peers() end)
    Process.send_after(self(), :ask, if(unset?, do: @soon, else: @later))
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end
end

