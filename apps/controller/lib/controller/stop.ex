defmodule Controller.Stop do
  @moduledoc """
  STOP from a page that isn't about one mount (Devices, Events, a camera's
  pages): every mount this machine can reach, on it or on a box, both axes.
  A page about one mount stops that one, its own way (the keypad also lets
  go of a held strip); this is for every other page, so every page has STOP.
  """

  @doc "Stop every mount in reach; a mount that doesn't answer is skipped, not waited on."
  def all do
    for m <- Mount.list() do
      try do
        Mount.stop(m)
      catch
        :exit, _ -> :not_answering
      end
    end

    :ok
  end
end
