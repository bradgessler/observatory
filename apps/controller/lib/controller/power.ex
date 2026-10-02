defmodule Controller.Power do
  @moduledoc """
  Whether the box's supply holds up. A Raspberry Pi says when its 5 V input
  sags below about 4.63 V (`rpi_volt`'s `in0_lcrit_alarm`, the kernel's
  `raspberrypi-hwmon`); everything on its USB ports, the camera and the
  mount's cable included, shares that supply, and a dip is what drops the
  USB hub (#106). This reads the alarm every second, counts the dips, emits
  an event on each, and says so on the pages in a line.

  Nothing to read (a Mac, an older kernel): `monitored: false`, no line.
  """
  use GenServer
  require Logger

  @every_ms 1_000
  @topic "power"

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: Keyword.get(opts, :name, __MODULE__))

  @doc "`%{monitored, low, dips, last_dip_at}`: low now, dips since boot, when the last began."
  def status(name \\ __MODULE__), do: :persistent_term.get({__MODULE__, name, :status}, %{monitored: false, low: false, dips: 0, last_dip_at: nil})

  def subscribe, do: Telescope.subscribe(@topic)

  @doc "One calm line for a page, or nil when there's nothing to say."
  def words(%{monitored: true, low: true}), do: "The box's power is low right now: the camera and the mount cable share it. Use a 5.1 V, 2.5 A supply, and a powered USB hub for the camera."

  def words(%{monitored: true, dips: n, last_dip_at: %DateTime{} = at}) when n > 0 do
    ago = DateTime.diff(DateTime.utc_now(), at)
    if ago < 3_600, do: "The box's power dipped #{n} #{if n == 1, do: "time", else: "times"} since it started, last #{minutes(ago)} ago. A 5.1 V, 2.5 A supply and a powered USB hub for the camera stop that."
  end

  def words(_), do: nil

  defp minutes(s) when s < 60, do: "#{s} s"
  defp minutes(s), do: "#{div(s, 60)} min"

  @impl true
  def init(opts) do
    alarm = Keyword.get_lazy(opts, :alarm, &find_alarm/0)
    s = %{alarm: alarm, low: false, dips: 0, last_dip_at: nil, name: Keyword.get(opts, :name, __MODULE__)}
    publish(s)
    if alarm, do: send(self(), :read)
    {:ok, s}
  end

  @impl true
  def handle_info(:read, s) do
    Process.send_after(self(), :read, @every_ms)
    low = read(s.alarm)

    s =
      cond do
        low and not s.low ->
          Logger.warning("power: under-voltage")
          Telescope.Events.emit(:power, :low, %{dips: s.dips + 1})
          %{s | low: true, dips: s.dips + 1, last_dip_at: DateTime.utc_now()} |> publish()

        not low and s.low ->
          Telescope.Events.emit(:power, :normal, %{})
          %{s | low: false} |> publish()

        true ->
          s
      end

    {:noreply, s}
  end

  defp read(path) do
    case File.read(path) do
      {:ok, v} -> String.trim(v) == "1"
      _ -> false
    end
  end

  # the hwmon device called rpi_volt, if there is one
  defp find_alarm do
    Path.wildcard("/sys/class/hwmon/hwmon*")
    |> Enum.find_value(fn d ->
      with {:ok, name} <- File.read(Path.join(d, "name")), "rpi_volt" <- String.trim(name), do: Path.join(d, "in0_lcrit_alarm"), else: (_ -> nil)
    end)
  end

  defp publish(s) do
    status = %{monitored: s.alarm != nil, low: s.low, dips: s.dips, last_dip_at: s.last_dip_at}
    :persistent_term.put({__MODULE__, s.name, :status}, status)
    Telescope.broadcast(@topic, {:power, status})
    s
  end
end
