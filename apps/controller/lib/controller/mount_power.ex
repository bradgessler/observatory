defmodule Controller.MountPower do
  @moduledoc """
  Remembers when each mount was last switched on (its counts restarted), in
  settings, so a never-zeroed alignment knows whether its counts still mean
  what they did, across Pi reboots and firmware upgrades. The driver sees the
  power-on (both axes back at their power-on value) and broadcasts it; a
  power-on it saw while this process was down is in its snapshot too.
  `Controller.Sky.Lineup.stale?/2` reads both. #91's journal will know for sure.

  The snapshot's one is written down here as well (`look/0`, every few
  seconds). The mount app starts before this process, so the power-on the
  driver sees as the box boots is said before anyone is listening: it lived
  only in the driver's memory, and the next reboot of the box forgot it. On
  12 October 2026 a firmware push did that, and an alignment from four
  nights before came back as "aligned, good for deep sky", with the side of
  the counterweight someone had told it that other night.
  """
  use GenServer

  alias Controller.Settings

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "When mount `id` was last switched on, in ms since the epoch, or nil."
  def last_on(id), do: Settings.get("mount_power_on", %{})[id]

  @impl true
  def init(_) do
    Telescope.subscribe("mount_power")
    send(self(), :look)
    {:ok, nil}
  end

  @look_ms 5_000

  @doc "Write down any power-on this machine's mount drivers have seen and this has not. Returns the ids it wrote."
  def look do
    for %{id: id} <- safe(fn -> Mount.local_list() end) || [],
        %{power_on_at: at} when is_integer(at) <- [safe(fn -> Mount.snapshot(id) end)],
        newer?(id, at) do
      record(id, at)
      id
    end
  end

  @impl true
  def handle_info({:mount_power_on, id, at}, s) do
    if newer?(id, at), do: record(id, at)
    {:noreply, s}
  end

  def handle_info(:look, s) do
    Process.send_after(self(), :look, @look_ms)
    look()
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp newer?(id, at), do: is_integer(at) and (not is_integer(last_on(id)) or at > last_on(id))

  defp record(id, at) do
    Settings.put("mount_power_on", Map.put(Settings.get("mount_power_on", %{}), id, at))
    Telescope.Events.emit(:lineup, :power_on, %{id: id, why: "the mount was switched on: an alignment from before no longer holds"})
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    :exit, _ -> nil
  end
end
