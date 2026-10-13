defmodule Controller.MountPowerTest do
  @moduledoc """
  When a mount was last switched on is what tells a never-zeroed alignment
  that its counts no longer mean what they did. It has to outlive the box's
  own restarts, including a power-on the driver saw before anything was
  listening for it.
  """
  use ExUnit.Case, async: false

  alias Controller.{MountPower, Settings}

  setup do
    id = "sim-power-#{System.unique_integer([:positive])}"
    on_exit(fn -> Settings.put("mount_power_on", Map.delete(Settings.get("mount_power_on", %{}), id)) end)
    %{id: id}
  end

  # 12 October 2026: the driver saw the mount switched on as the box booted, before this was
  # listening. It was only in the driver's memory, a firmware push restarted the box, and an
  # alignment from four nights before came back as good.
  test "a power-on that is only in the driver's snapshot is written down", %{id: id} do
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true, power_on_at: at}} when is_integer(at), 2_000

    # as if the broadcast had gone out before anyone listened
    Process.sleep(100)
    Settings.put("mount_power_on", Map.delete(Settings.get("mount_power_on", %{}), id))
    assert MountPower.last_on(id) == nil

    assert id in MountPower.look()
    assert MountPower.last_on(id) == at
    # once written, a second look has nothing to add
    refute id in MountPower.look()
  end

  test "an older power-on never replaces a newer one", %{id: id} do
    Settings.put("mount_power_on", Map.put(Settings.get("mount_power_on", %{}), id, 2_000))
    send(Process.whereis(MountPower), {:mount_power_on, id, 1_000})
    :sys.get_state(MountPower)
    assert MountPower.last_on(id) == 2_000
    send(Process.whereis(MountPower), {:mount_power_on, id, 3_000})
    :sys.get_state(MountPower)
    assert MountPower.last_on(id) == 3_000
  end
end
