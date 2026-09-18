defmodule Mount do
  @moduledoc """
  Public API for mounts anywhere in the cluster.

  A mount is addressed by a `ref`: either a bare id (local node) or the
  `%{id: id, node: node}` map that `list/0` returns. Rates are in multiples
  of sidereal; positive is the mount's "forward" direction, negative reverse.

      iex> [m] = Mount.list()
      iex> Mount.slew(m, :ra, 64)      # start moving RA at 64× sidereal
      iex> Mount.stop(m, :ra)
      iex> Mount.goto_relative(m, :dec, 5.0)
      iex> Mount.track(m, :sidereal)
  """

  alias Mount.Server

  @type ref :: String.t() | %{id: String.t(), node: node}
  @type axis :: :ra | :dec

  @doc "Every mount on every connected node."
  def list do
    Telescope.nodes()
    |> Enum.flat_map(fn n ->
      try do
        :erpc.call(n, __MODULE__, :local_list, [], 2_000)
      catch
        _, _ -> []
      end
    end)
  end

  @doc false
  def local_list do
    Registry.select(Mount.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Enum.sort()
    |> Enum.map(&%{id: &1, node: node()})
  end

  def snapshot(ref), do: call(ref, :snapshot)

  @doc "Run an axis at `rate` × sidereal until told otherwise. `hold: true` makes it self-stop unless refreshed."
  def slew(ref, axis, rate, opts \\ []), do: call(ref, {:slew, axis, rate / 1, opts})

  def stop(ref, axis \\ :both), do: call(ref, {:stop, axis})

  @doc "Instant stop of both axes, no ramp-down."
  def emergency_stop(ref), do: call(ref, :emergency_stop)

  @doc "Move an axis by `degrees` at full goto speed (mount-managed ramps)."
  def goto_relative(ref, axis, degrees), do: call(ref, {:goto_relative, axis, degrees / 1})

  @doc "`:sidereal`, `:lunar`, `:solar` or `:off`."
  def track(ref, mode), do: call(ref, {:track, mode})

  @doc "Declare the current pointing to be the home position (counterweight down, scope at the pole)."
  def set_home(ref), do: call(ref, :set_home)

  @doc "Send a raw protocol frame, e.g. `Mount.raw(m, \":e1\\r\")`. For poking."
  def raw(ref, frame), do: call(ref, {:raw, frame})

  def subscribe(%{id: id}), do: Telescope.subscribe("mount:#{id}")
  def subscribe(id), do: Telescope.subscribe("mount:#{id}")

  defp call(%{id: id, node: n}, msg) when n == node(), do: Server.call(id, msg)
  defp call(%{id: id, node: n}, msg), do: :erpc.call(n, Server, :call, [id, msg], 15_000)
  defp call(id, msg) when is_binary(id), do: Server.call(id, msg)
end
