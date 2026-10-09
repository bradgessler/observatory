defmodule Controller.Frames.SpoolIndex do
  @moduledoc """
  The frames spool's index in the database: a `frames` row per file on this
  machine's card (`place: "spool"`), its state (ready, leased, sent) and the
  camera's record, so the box can say what it's holding and since when.

  A spool that had `.meta` files from before the database brings them in
  once and deletes them. If the database isn't up, the spool uses the
  `.meta` files instead (`Queues.Spool.Files`) and nothing is lost: the
  files on the card are the truth either way.
  """
  @behaviour Queues.Spool.Index

  import Ecto.Query
  alias Controller.Frames.Frame
  alias Controller.Repo
  alias Queues.Spool.Files

  @impl true
  def load(name, dir) do
    # from before the database: brought in once; a .meta whose file is gone just goes
    for e <- Files.load(name, dir) do
      put(name, dir, e)
      Files.delete(name, dir, e.id)
    end

    for meta <- Path.wildcard(Path.join(dir, "*.meta")), do: File.rm(meta)

    # this spool's rows: the ones whose file is (or was) in its directory
    rows = Repo.all(from f in Frame, where: f.place == "spool") |> Enum.filter(&(Path.dirname(&1.path || "") == dir))
    {here, gone} = Enum.split_with(rows, &File.exists?(Path.join(dir, &1.id)))
    # a row whose file is gone (deleted by hand, a card swapped) goes too
    for f <- gone, do: Repo.delete_all(from x in Frame, where: x.place == "spool" and x.id == ^f.id)

    Enum.map(here, fn f ->
      %{id: f.id, bytes: f.bytes, sha256: f.sha256, meta: %{seq: f.seq}, at_ms: f.put_at_ms, state: String.to_existing_atom(f.state)}
    end)
  end

  @impl true
  def put(_name, dir, entry) do
    record = get_in(entry, [:meta, :record]) || %{}

    attrs =
      Map.merge(Frame.from_record(record), %{
        place: "spool",
        id: entry.id,
        state: to_string(entry.state),
        path: Path.join(dir, entry.id),
        bytes: entry.bytes,
        sha256: entry.sha256,
        put_at_ms: entry.at_ms,
        box: to_string(node())
      })

    %Frame{}
    |> Frame.changeset(attrs)
    |> Repo.insert!(on_conflict: {:replace_all_except, [:inserted_at]}, conflict_target: [:place, :id])

    :ok
  end

  @impl true
  def update(_name, _dir, entry) do
    from(f in Frame, where: f.place == "spool" and f.id == ^entry.id)
    |> Repo.update_all(set: [state: to_string(entry.state), updated_at: DateTime.utc_now()])

    :ok
  end

  @impl true
  def delete(_name, _dir, id) do
    Repo.delete_all(from f in Frame, where: f.place == "spool" and f.id == ^id)
    :ok
  end
end
