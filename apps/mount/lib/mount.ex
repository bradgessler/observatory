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

  @doc """
  Every mount on every connected node, except other machines' simulators.

  A simulator exists for the machine running it (a Mac with no cable). Listed
  on a box joined to that Mac, it became the box's default and the box's own
  keypad drove the Mac's simulator while the real telescope sat still. So a
  simulator is only ever listed where it runs.
  """
  def list do
    Telescope.nodes()
    |> Enum.flat_map(fn n ->
      try do
        :erpc.call(n, __MODULE__, :local_list, [], 2_000)
      catch
        _, _ -> []
      end
    end)
    |> Enum.filter(&listed?(&1, node()))
  end

  @doc false
  # the rule itself is Telescope.listed?/3, the same for every device
  def listed?(%{node: n} = ref, here), do: Telescope.listed?(n, simulated?(ref), here)

  @doc false
  def local_list do
    Registry.select(Mount.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Enum.sort()
    |> Enum.map(&%{id: &1, node: node()})
  end

  def snapshot(ref), do: call(ref, :snapshot)

  @doc "Is this a simulated mount? One rule, so no page invents its own."
  def simulated?(id) when is_binary(id), do: String.starts_with?(id, "sim")
  def simulated?(%{id: id}), do: simulated?(id)
  def simulated?(_), do: false

  @doc """
  The mount a page drives when none was asked for: a real telescope before a
  simulator (a Mac with no cable runs one, and a box's scope joined over the
  network must win over it), then by id. Takes ids or refs; `nil` for none.
  """
  def default(mounts) do
    mounts
    |> Enum.sort_by(&{simulated?(&1), id_of(&1)})
    |> List.first()
  end

  @doc """
  Run an axis at `rate` × sidereal until told otherwise. `hold: true` makes it
  self-stop unless refreshed. `quiet: true` skips the event (for a refresh of a
  slew already reported, e.g. the tracker feeding its dead-man).
  """
  def slew(ref, axis, rate, opts \\ []) do
    call(ref, {:slew, axis, rate / 1, Keyword.delete(opts, :quiet)})
    |> logged(opts[:quiet] != true, :slew, %{id: id_of(ref), axis: axis, rate: rate / 1, hold: Keyword.get(opts, :hold, false)})
  end

  # events say what the scope did, so a refused command (limit, not connected) is not one
  defp logged(result, true, what, data) do
    if result == :ok, do: Telescope.Events.emit(:mount, what, data)
    result
  end

  defp logged(result, _, _, _), do: result

  @doc "Ramped stop of an axis (or both). `instant: true` halts one axis with no ramp — for dead-man releases."
  def stop(ref, axis \\ :both, opts \\ [])
  def stop(ref, axis, instant: true) when axis in [:ra, :dec] do
    call(ref, {:stop, axis, :instant}) |> logged(true, :stop, %{id: id_of(ref), axis: axis, instant: true})
  end

  def stop(ref, axis, _opts) do
    call(ref, {:stop, axis}) |> logged(true, :stop, %{id: id_of(ref), axis: axis})
  end

  @doc "Instant stop of both axes, no ramp-down."
  def emergency_stop(ref) do
    call(ref, :emergency_stop) |> logged(true, :emergency_stop, %{id: id_of(ref)})
  end

  @doc "Move an axis by `degrees` at full goto speed (mount-managed ramps)."
  def goto_relative(ref, axis, degrees) do
    call(ref, {:goto_relative, axis, degrees / 1}) |> logged(true, :goto, %{id: id_of(ref), axis: axis, degrees: degrees / 1})
  end

  @doc "`:sidereal`, `:lunar`, `:solar` or `:off`."
  def track(ref, mode) do
    call(ref, {:track, mode}) |> logged(true, :track, %{id: id_of(ref), mode: mode})
  end

  @doc """
  Declare the current pointing to be home (counterweight down, scope at the
  pole). Zeroes both axes and arms the soft limits (`config :mount, :limits`):
  from here on a goto past a limit returns `{:error, :limit}` and a slew that
  reaches one is stopped there.
  """
  def set_home(ref) do
    call(ref, :set_home) |> logged(true, :set_home, %{id: id_of(ref)})
  end

  @doc "Send a raw protocol frame, e.g. `Mount.raw(m, \":e1\\r\")`. For poking."
  def raw(ref, frame), do: call(ref, {:raw, frame})

  @doc "Runtime knobs: `tracking_direction: :forward | :reverse`, `limits: map | nil`."
  def configure(ref, opts), do: call(ref, {:configure, opts})

  # -- devices (local node) -------------------------------------------------------

  @doc "Serial ports this machine sees, with what we make of each."
  defdelegate ports, to: Mount.Discovery

  @doc "Rescan USB right now."
  defdelegate scan, to: Mount.Discovery

  @doc "Start a driver on a specific serial port."
  def connect_port(port), do: Mount.Discovery.add_port(port)

  @doc "Stop a driver started by hand."
  def disconnect_port(port), do: Mount.Discovery.remove_port(port)

  @doc "Last scan time, hand-added ports, running ids."
  defdelegate discovery_status, to: Mount.Discovery, as: :status

  def subscribe(%{id: id}), do: Telescope.subscribe("mount:#{id}")
  def subscribe(id), do: Telescope.subscribe("mount:#{id}")

  defp id_of(%{id: id}), do: id
  defp id_of(id) when is_binary(id), do: id

  defp call(%{id: id, node: n}, msg) when n == node(), do: Server.call(id, msg)
  defp call(%{id: id, node: n}, msg), do: :erpc.call(n, Server, :call, [id, msg], 15_000)
  defp call(id, msg) when is_binary(id), do: Server.call(id, msg)
end
