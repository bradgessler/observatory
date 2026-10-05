defmodule Telescope.ClusterTest do
  @moduledoc """
  Tests never talk to the LAN. `config :libcluster, topologies: []` in
  config/test.exs looked like it switched the gossip off and did nothing:
  Config merges keyword lists, and an empty one merged into config.exs's
  `[lan: ...]` leaves it standing. So every `mix test` multicast heartbeats
  on UDP 45892, on the same network as a telescope in use.
  """
  use ExUnit.Case, async: true

  test "no cluster strategy runs under test" do
    assert Supervisor.which_children(Telescope.ClusterSupervisor) == []
  end

  test "an environment says :none to switch the gossip off; a list is used as it is" do
    was = Application.get_env(:libcluster, :topologies)
    on_exit(fn -> Application.put_env(:libcluster, :topologies, was) end)

    Application.put_env(:libcluster, :topologies, :none)
    assert Telescope.Application.topologies() == []

    lan = [lan: [strategy: Cluster.Strategy.Gossip]]
    Application.put_env(:libcluster, :topologies, lan)
    assert Telescope.Application.topologies() == lan

    Application.delete_env(:libcluster, :topologies)
    assert Telescope.Application.topologies() == []
  end
end
