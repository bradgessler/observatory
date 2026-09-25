defmodule Firmware.AppRestarter do
  @moduledoc """
  What happens when one of the box's own apps stops: it is started again.

  An app stops when its top supervisor gives up (its children crashed faster
  than its restart budget). Shoehorn's default is to carry on without it, which
  leaves the box up but, say, with no mount driver until someone reboots it.
  This starts it again after 2 s, up to 5 times in 10 minutes; past that it
  stays stopped and the log says so, rather than looping on something broken.
  Anything else stopping (a library, the system's own) is left to Shoehorn's
  default: carry on.
  """
  @behaviour Shoehorn.Handler
  require Logger

  @ours [:telescope, :mount, :controller, :watch, :video, :input]
  @budget 5
  @window_s 600

  @impl true
  def init(_opts), do: {:ok, %{}}

  @impl true
  def application_started(_app, state), do: {:continue, state}

  @impl true
  def application_exited(app, reason, state) when app in @ours do
    now = System.monotonic_time(:second)
    recent = state |> Map.get(app, []) |> Enum.filter(&(now - &1 < @window_s))

    if length(recent) < @budget do
      Logger.error("#{app} stopped (#{inspect(reason)}); starting it again in 2 s")

      spawn(fn ->
        Process.sleep(2_000)
        Application.ensure_all_started(app)
      end)

      {:continue, Map.put(state, app, [now | recent])}
    else
      Logger.error("#{app} stopped #{@budget} times in #{div(@window_s, 60)} minutes; leaving it stopped until a reboot")
      {:continue, state}
    end
  end

  def application_exited(_app, _reason, state), do: {:continue, state}
end
