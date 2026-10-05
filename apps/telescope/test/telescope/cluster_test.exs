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

  # A dev server started for something else joined the telescope box in use
  # that night, and its simulated camera showed there as live frames (#121).
  # The box never gossips: the Mac joined it through Telescope.Boxes, which
  # rejoins every box in ~/.observatory/boxes.txt once this machine is a node.
  # So a dev build is not a node at all, and does not gossip either, unless it
  # is started with OBSERVATORY_CLUSTER=1.
  test "a dev build stays out of the cluster unless it is started with OBSERVATORY_CLUSTER=1" do
    alone = config(:dev, nil)
    assert topologies(alone) == []
    assert alone[:telescope][:distribution] == nil

    # only "1" says yes
    assert topologies(config(:dev, "0")) == []
    assert config(:dev, "0")[:telescope][:distribution] == nil

    joined = config(:dev, "1")
    assert topologies(joined) == [lan: [strategy: Cluster.Strategy.Gossip]]
    assert joined[:telescope][:distribution][:name] == "observatory"
    assert joined[:telescope][:boxes_file] =~ ".observatory/boxes.txt"
  end

  test "a rehearsal is all simulators, so it never joins, whatever dev was told" do
    for told <- [nil, "1"] do
      rehearsal = config(:rehearsal, told)
      assert topologies(rehearsal) == []
      assert rehearsal[:telescope][:distribution] == nil
    end
  end

  @config Path.expand("../../../../config/config.exs", __DIR__)

  # the project's config as `env` loads it, with OBSERVATORY_CLUSTER set to `told` (nil: not set)
  defp config(env, told) do
    was = System.get_env("OBSERVATORY_CLUSTER")
    set = fn value -> if value, do: System.put_env("OBSERVATORY_CLUSTER", value), else: System.delete_env("OBSERVATORY_CLUSTER") end
    set.(told)

    try do
      Config.Reader.read!(@config, env: env)
    after
      set.(was)
    end
  end

  # what Telescope.Application makes of a config's gossip setting
  defp topologies(config) do
    was = Application.get_env(:libcluster, :topologies)
    Application.put_env(:libcluster, :topologies, config[:libcluster][:topologies])

    try do
      Telescope.Application.topologies()
    after
      Application.put_env(:libcluster, :topologies, was)
    end
  end
end
