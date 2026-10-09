defmodule Controller.Viewer do
  @moduledoc """
  Who's looking: a random id kept in each browser's session (a plug on every
  page), so things that are one viewer's and not everyone's, the time they've
  set the sky to, the chart they picked, follow them from page to page
  without being anyone else's. The telescope this viewer drives works the
  same way (`Controller.TelescopeController`).

  The things themselves are in `prefs`: a small table on this machine, by
  viewer, each value dropped when it hasn't been touched for `@keep_ms` (a
  night). Lost on a restart, which is fine: they're conveniences, never the
  telescope's state.

      Viewer.get(session["viewer"], :sky_view, "dome")
      Viewer.put(session["viewer"], :sky_shift, 60)
  """
  @behaviour Plug
  use Agent

  @keep_ms 12 * 3_600_000

  # -- the plug ---------------------------------------------------------------------------

  @impl Plug
  def init(opts), do: opts

  @impl Plug
  def call(conn, _opts) do
    case Plug.Conn.get_session(conn, "viewer") do
      nil -> Plug.Conn.put_session(conn, "viewer", Base.url_encode64(:crypto.strong_rand_bytes(12), padding: false))
      _ -> conn
    end
  end

  # -- the prefs --------------------------------------------------------------------------

  def start_link(_), do: Agent.start_link(fn -> %{} end, name: __MODULE__)

  @doc "A viewer's value for `key`, or `default` (also with no viewer, or the table down)."
  def get(nil, _key, default), do: default

  def get(viewer, key, default) do
    Agent.get(__MODULE__, fn m ->
      case m[{viewer, key}] do
        {v, at} -> if now() - at < @keep_ms, do: v, else: default
        _ -> default
      end
    end)
  catch
    :exit, _ -> default
  end

  @doc "Keep `value` for a viewer (dropping anyone's that have gone stale)."
  def put(nil, _key, _value), do: :ok

  def put(viewer, key, value) do
    Agent.update(__MODULE__, fn m ->
      t = now()
      m |> Map.filter(fn {_, {_, at}} -> t - at < @keep_ms end) |> Map.put({viewer, key}, {value, t})
    end)
  catch
    :exit, _ -> :ok
  end

  defp now, do: System.monotonic_time(:millisecond)
end
