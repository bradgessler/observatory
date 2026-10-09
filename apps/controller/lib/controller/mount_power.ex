defmodule Controller.MountPower do
  @moduledoc """
  Remembers when each mount was last switched on (its counts restarted), in
  settings, so a never-zeroed alignment knows whether its counts still mean
  what they did, across Pi reboots and firmware upgrades. The driver sees the
  power-on (both axes back at their power-on value) and broadcasts it; a
  power-on it saw while this process was down is in its snapshot too.
  `Controller.Sky.Lineup.stale?/2` reads both. #91's journal will know for sure.
  """
  use GenServer

  alias Controller.Settings

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "When mount `id` was last switched on, in ms since the epoch, or nil."
  def last_on(id), do: Settings.get("mount_power_on", %{})[id]

  @impl true
  def init(_) do
    Telescope.subscribe("mount_power")
    {:ok, nil}
  end

  @impl true
  def handle_info({:mount_power_on, id, at}, s) do
    Settings.put("mount_power_on", Map.put(Settings.get("mount_power_on", %{}), id, at))
    Telescope.Events.emit(:lineup, :power_on, %{id: id, why: "the mount was switched on: an alignment from before no longer holds"})
    {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}
end
