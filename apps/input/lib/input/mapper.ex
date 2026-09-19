defmodule Input.Mapper do
  @moduledoc """
  Drives a mount from input devices, server-side, no browser required.

  Subscribes to every device's state, runs `Input.Gamepad.interpret/2`, and
  turns the result into held slews (the driver's deadman still applies: if
  reports stop, the mount stops within a second), nudges, or an emergency
  stop. Starts **disarmed**; arm it from the UI once you can see what the pad
  is doing. The target mount defaults to the first one the cluster knows.
  """
  use GenServer

  alias Input.Gamepad

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def status, do: GenServer.call(__MODULE__, :status)
  def arm(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:arm, on?})
  def target(mount_id), do: GenServer.call(__MODULE__, {:target, mount_id})
  def configure(map) when is_map(map), do: GenServer.call(__MODULE__, {:configure, map})

  @impl true
  def init(_) do
    Telescope.subscribe("input")
    {:ok, %{armed: false, target: nil, map: %{}, held: [], last: %{}, action: :idle, start: nil}}
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, public(s), s}

  def handle_call({:arm, on?}, _from, s) do
    s = if on?, do: %{s | armed: true}, else: %{release(s) | armed: false}
    {:reply, :ok, announce(s)}
  end

  def handle_call({:target, id}, _from, s), do: {:reply, :ok, announce(%{release(s) | target: id})}
  def handle_call({:configure, map}, _from, s), do: {:reply, :ok, announce(%{s | map: Map.merge(s.map, map)})}

  @impl true
  def handle_info({:input, id, %{state: state}}, s) do
    action = Gamepad.interpret(state, s.map)
    s = %{s | last: Map.put(s.last, id, state), action: action}

    s =
      case {s.armed, ref(s), action} do
        {false, _, _} -> s
        {_, nil, _} -> s
        {_, ref, :stop} ->
          safe(fn -> Mount.emergency_stop(ref) end)
          %{s | held: []}

        {_, ref, {_kind, rates}} ->
          for {axis, r} <- rates, do: safe(fn -> Mount.slew(ref, axis, r, hold: true) end)
          %{s | held: Enum.map(rates, &elem(&1, 0))}

        {_, _ref, :idle} ->
          release(s)
      end

    {:noreply, announce(s)}
  end

  def handle_info({:input_gone, _id}, s), do: {:noreply, announce(release(s))}
  def handle_info(_, s), do: {:noreply, s}

  defp ref(%{target: nil}), do: Mount.list() |> List.first()
  defp ref(%{target: id}), do: Enum.find(Mount.list(), &(&1.id == id))

  defp release(%{held: []} = s), do: s

  defp release(s) do
    case ref(s) do
      nil -> :ok
      ref ->
        snap = safe(fn -> Mount.snapshot(ref) end)

        for axis <- s.held do
          if axis == :ra and is_map(snap) and snap.tracking != :off,
            do: safe(fn -> Mount.track(ref, snap.tracking) end),
            else: safe(fn -> Mount.stop(ref, axis) end)
        end
    end

    %{s | held: []}
  end

  defp public(s) do
    %{armed: s.armed, target: (ref(s) || %{})[:id], action: s.action, action_text: Gamepad.describe(s.action), held: s.held, map: Map.merge(Gamepad.defaults(), s.map)}
  end

  defp announce(s) do
    Telescope.broadcast("input", {:mapper, public(s)})
    s
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end
end
