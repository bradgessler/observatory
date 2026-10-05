defmodule Telescope.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children =
      [
        {Phoenix.PubSub, name: Telescope.PubSub},
        Telescope.Events,
        {Cluster.Supervisor, [topologies(), [name: Telescope.ClusterSupervisor]]}
      ] ++ cluster_children()

    Supervisor.start_link(children, strategy: :one_for_one, name: Telescope.Supervisor)
  end

  # An environment that wants no LAN gossip says `topologies: :none`. It cannot
  # say `[]`: Config merges keyword lists, and an empty one merged into
  # config.exs's `[lan: ...]` leaves the gossip running (test and rehearsal
  # both said `[]` and both multicast on UDP 45892 all the same).
  @doc false
  def topologies do
    case Application.get_env(:libcluster, :topologies, []) do
      list when is_list(list) -> list
      _none -> []
    end
  end

  # This machine joins the cluster and finds boxes only when configured to (the
  # Mac in development); a box starts its own distribution.
  defp cluster_children do
    case Application.get_env(:telescope, :distribution) do
      nil -> []
      opts -> [{Telescope.Distribution, opts}, {Telescope.Boxes, file: Application.get_env(:telescope, :boxes_file)}]
    end
  end
end
