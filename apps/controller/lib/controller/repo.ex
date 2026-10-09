defmodule Controller.Repo do
  @moduledoc """
  This machine's database: SQLite, through Ecto, migrated at every boot
  (`Controller.Repo.Supervisor`). It holds the settings (`Controller.Settings`)
  and the frames (`Controller.Frames.Frame`): on a box the frames waiting on
  its card for the Mac, on the Mac the frames copied to it, each with its
  FITS header, so "last night's frames with stars" is a query.

  The file is `~/.observatory/observatory.db` (`/data/observatory/observatory.db`
  on a box), in WAL mode so a page reading never waits on a frame being
  written. Pictures are never in it: they're files, streamed to the Mac and
  deleted for room at once; blobs in SQLite on an SD card would mean write
  amplification and VACUUM to get the space back.
  """
  use Ecto.Repo, otp_app: :controller, adapter: Ecto.Adapters.SQLite3

  @impl true
  def init(_type, config) do
    {:ok, Keyword.put_new_lazy(config, :database, &default_path/0)}
  end

  @doc "Where the database is when config doesn't say."
  def default_path, do: Path.join([System.user_home!(), ".observatory", "observatory.db"])

  @doc "Is the database up (opened and migrated)? Everything that uses it has a way to carry on when it isn't."
  def up?, do: Process.whereis(__MODULE__) != nil and :persistent_term.get({__MODULE__, :migrated}, false)
end
