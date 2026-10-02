defmodule Controller.Repo.Supervisor do
  @moduledoc """
  The database's own branch (#91's boot order): open it, back it up if this
  firmware has migrations it hasn't run, migrate, and say so. The mount, the
  pad and the pages never wait on it and never fall with it: if the file
  can't be opened or a migration fails, this branch gives up alone, logs
  why (`error/0`), and the settings carry on from the JSON file.
  """
  use Supervisor
  require Logger

  alias Controller.Repo

  def child_spec(opts), do: %{id: __MODULE__, start: {__MODULE__, :start_link, [opts]}, type: :supervisor, restart: :transient}

  def start_link(opts \\ []) do
    case Supervisor.start_link(__MODULE__, opts, name: __MODULE__) do
      {:ok, pid} ->
        {:ok, pid}

      {:error, reason} ->
        Logger.error("database: didn't start (#{inspect(reason) |> String.slice(0, 300)}); settings carry on from settings.json")
        :persistent_term.put({__MODULE__, :error}, reason)
        :ignore
    end
  end

  @doc "Why the database isn't up, or nil."
  def error, do: :persistent_term.get({__MODULE__, :error}, nil)

  @impl true
  def init(_opts) do
    :persistent_term.put({Repo, :migrated}, false)
    path = Keyword.get(Application.get_env(:controller, Repo, []), :database) || Repo.default_path()
    File.mkdir_p!(Path.dirname(path))

    children = [
      Repo,
      # a copy of the file before any migration this firmware brings, then the migrations
      {Task, fn -> backup(path) end} |> Supervisor.child_spec(id: :backup, restart: :temporary),
      {Ecto.Migrator, repos: [Repo], skip: false},
      # said in the start itself, not a task: whatever starts after this branch (Settings) sees it
      %{id: :migrated, start: {__MODULE__, :migrated, []}, restart: :temporary}
    ]

    Supervisor.init(children, strategy: :rest_for_one, max_restarts: 3, max_seconds: 30)
  end

  @doc false
  def migrated do
    :persistent_term.put({Repo, :migrated}, true)
    :ignore
  end

  defp backup(path) do
    pending = Ecto.Migrator.migrations(Repo) |> Enum.filter(fn {state, _, _} -> state == :down end)

    if pending != [] and File.exists?(path) and File.stat!(path).size > 0 do
      {_, version, _} = List.last(pending)
      File.cp!(path, "#{path}.before-#{version}")
      Logger.info("database: backed up before #{length(pending)} migration(s)")
    end
  end
end
