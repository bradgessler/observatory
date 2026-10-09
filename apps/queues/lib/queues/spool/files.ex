defmodule Queues.Spool.Files do
  @moduledoc """
  The default spool index: beside each file a small `<id>.meta` (the entry,
  as an Erlang term). Crash-safe (written after the file is in place, read
  back at start) and needing nothing, but not something to query.
  """
  @behaviour Queues.Spool.Index

  @impl true
  def load(_name, dir) do
    for meta <- Path.wildcard(Path.join(dir, "*.meta")),
        {:ok, bin} <- [File.read(meta)],
        %{id: id} = e <- [safe_decode(bin)],
        File.exists?(Path.join(dir, id)),
        do: e
  end

  @impl true
  def put(_name, dir, entry), do: write(dir, entry)

  @impl true
  def update(_name, dir, entry), do: write(dir, entry)

  @impl true
  def delete(_name, dir, id) do
    File.rm(Path.join(dir, id <> ".meta"))
    :ok
  end

  defp write(dir, entry) do
    File.write!(Path.join(dir, entry.id <> ".meta"), :erlang.term_to_binary(Map.take(entry, [:id, :bytes, :sha256, :meta, :at_ms, :state])))
    :ok
  end

  @doc false
  def safe_decode(bin) do
    :erlang.binary_to_term(bin, [:safe])
  rescue
    _ -> nil
  end
end
