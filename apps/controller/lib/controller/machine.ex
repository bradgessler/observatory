defmodule Controller.Machine do
  @moduledoc """
  The machine a telescope is plugged into, and asking it.

  A telescope's alignment, its hold and its log live on the machine its mount
  is plugged into: that machine's settings, that machine's processes. A page
  on another machine of the cluster (a Mac used as the terminal for a box, or
  for several) must not answer from its own: on 13 October 2026 the Mac's
  Tonight said "Not aligned yet" for a telescope the box had aligned to one
  arcminute. So everything about a telescope is asked of its own machine,
  the way the mount driver (`Mount`) and the stills camera already are:

      Machine.route("ttyUSB0", {Lineup, :status, ["ttyUSB0"]}, default, fn -> ...here... end)

  runs the function when the telescope is this machine's, and otherwise calls
  the same function there, answering `default` when that machine cannot be
  reached. One terminal, many telescopes (#143).
  """

  @key {__MODULE__, :nodes}
  @timeout 2_000

  @doc "Which machine mount `id` is plugged into (its node); this one when nobody knows."
  def of(id) when is_binary(id) do
    case :persistent_term.get(@key, %{}) do
      %{^id => node} -> node
      _ -> look(id)
    end
  end

  def of(%{node: node}), do: node
  def of(_), do: node()

  @doc "The machine `id` is on when it is not this one, else nil."
  def away(id) do
    case of(id) do
      n when n == node() -> nil
      n -> n
    end
  end

  @doc """
  Answer a question about telescope `id` on its own machine: `here.()` when
  that is this one, else `{module, function, args}` called there. `default`
  when that machine is not connected or does not answer in time.
  """
  def route(id, {m, f, a}, default, here) when is_function(here, 0) do
    case away(id) do
      nil -> here.()
      node -> ask(node, m, f, a, default)
    end
  end

  @doc "Call `m.f(a)` on `node`, or `default` when it is not connected or fails."
  def ask(node, m, f, a, default \\ nil) do
    if node in Node.list(), do: :erpc.call(node, m, f, a, @timeout), else: default
  catch
    _, _ -> default
  end

  @doc "Remember where each mount is (`[%{id, node}]`, `Mount.list/0`), for `of/1`. Kept current by `Controller.ScopeNow`."
  def note(refs) do
    now = Map.new(refs, &{&1.id, &1.node})
    if now != :persistent_term.get(@key, %{}), do: :persistent_term.put(@key, now)
    :ok
  end

  # a mount nobody has noted yet (just plugged in, or asked before the first look)
  defp look(id) do
    case Enum.find(Mount.list(), &(&1.id == id)) do
      %{node: node} -> node
      _ -> node()
    end
  catch
    _, _ -> node()
  end
end
