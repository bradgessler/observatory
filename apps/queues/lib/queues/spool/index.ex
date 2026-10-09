defmodule Queues.Spool.Index do
  @moduledoc """
  Where a spool keeps its list of files and their states, apart from the
  files themselves. `Queues.Spool.Files` (a small `.meta` beside each file)
  is the default and needs nothing; an application with a database passes
  its own (`index: Controller.Frames.SpoolIndex`) so the list is queryable.

  Every callback gets the spool's name and directory. Entries are maps:
  `%{id, bytes, sha256, meta, at_ms, state}`, `state` one of `:ready`,
  `:leased`, `:sent`.
  """

  @doc "What was there before a restart. Leased files come back ready."
  @callback load(name :: term, dir :: Path.t()) :: [map]
  @callback put(name :: term, dir :: Path.t(), entry :: map) :: :ok
  @callback update(name :: term, dir :: Path.t(), entry :: map) :: :ok
  @callback delete(name :: term, dir :: Path.t(), id :: String.t()) :: :ok
end
