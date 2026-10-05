defmodule Telescope.ListedTest do
  @moduledoc """
  A simulated device is listed only on the node that runs it. A Mac's
  simulated telescope camera once showed on a box that had no camera of its
  own as live frames of 24 stars, and the owner tried to focus on them. One
  rule, here, for every device: mounts, the telescope camera, the stills
  camera.
  """
  use ExUnit.Case, async: true

  @box :"telescope@observatory.local"
  @mac :"observatory@mac.local"

  test "a simulated device is listed where it runs and nowhere else; a real one everywhere" do
    assert Telescope.listed?(@mac, true, @mac)
    refute Telescope.listed?(@mac, true, @box)
    assert Telescope.listed?(@box, false, @box)
    assert Telescope.listed?(@box, false, @mac)
    # a device that doesn't say is a real one
    assert Telescope.listed?(@box, nil, @mac)
    # and with no machine given it is this one that asks
    assert Telescope.listed?(node(), true)
    refute Telescope.listed?(@mac, true)
  end

  test "of two devices, one of them a simulator on another node, this node's list has only the real one" do
    devices = [%{id: "sim-camera", node: @mac, sim: true}, %{id: "sv105c", node: @box, sim: false}]

    assert [%{id: "sv105c"}] = Enum.filter(devices, &Telescope.listed?(&1.node, &1.sim, @box))
    # the Mac runs the simulator, so its own list has both
    assert [_, _] = Enum.filter(devices, &Telescope.listed?(&1.node, &1.sim, @mac))
  end

  # No second node here, so this watches which broadcast is made: the one that
  # goes to every node, or the one that stays on this machine.
  test "a simulated device's news stays on this machine; a real one's goes to the cluster" do
    Telescope.subscribe("listed-test")
    test = self()

    sender =
      spawn_link(fn ->
        receive do
          :go ->
            Telescope.broadcast("listed-test", :simulator, simulated: true)
            Telescope.broadcast("listed-test", :real, simulated: false)
            Telescope.broadcast("listed-test", :unsaid, [])
            send(test, :sent)
        end
      end)

    for name <- [:broadcast, :local_broadcast], do: :erlang.trace_pattern({Phoenix.PubSub, name, 3}, true, [])
    on_exit(fn -> for name <- [:broadcast, :local_broadcast], do: :erlang.trace_pattern({Phoenix.PubSub, name, 3}, false, []) end)
    :erlang.trace(sender, true, [:call])
    send(sender, :go)
    assert_receive :sent
    delivered = :erlang.trace_delivered(sender)
    assert_receive {:trace_delivered, ^sender, ^delivered}

    # this machine hears all three
    for news <- [:simulator, :real, :unsaid], do: assert_receive(^news)

    calls = for {:trace, ^sender, :call, {Phoenix.PubSub, name, [Telescope.PubSub, "listed-test", news]}} <- messages(), do: {name, news}
    assert calls == [local_broadcast: :simulator, broadcast: :real, broadcast: :unsaid]
  end

  defp messages do
    receive do
      message -> [message | messages()]
    after
      0 -> []
    end
  end
end
