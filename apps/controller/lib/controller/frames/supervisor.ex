defmodule Controller.Frames.Supervisor do
  @moduledoc """
  The frames pipeline's subtree (`Controller.Frames`): on every machine the
  `frames.write` queue and the `frames` spool, and on a machine that pulls
  (the Mac) the puller and the `frames.fetch` and `frames.measure` queues.
  A frame that fails is one failed frame. If a step keeps crashing (5
  restarts in 30 s) this gives up and stops: a transient child, so the
  camera keeps taking pictures (keeping them just says it can't) and the
  mount never notices.
  """
  use Supervisor

  alias Controller.Frames

  def start_link(opts \\ []), do: Supervisor.start_link(__MODULE__, opts, name: __MODULE__)

  def child_spec(opts), do: %{id: __MODULE__, start: {__MODULE__, :start_link, [opts]}, type: :supervisor, restart: :transient}

  @impl true
  def init(_opts) do
    spool = Application.get_env(:controller, :frames, []) |> Keyword.take([:budget_bytes, :min_free_bytes])

    # the spool's list of files in the database when it's up, else in small files beside them
    index = if Controller.Repo.up?(), do: Controller.Frames.SpoolIndex, else: Queues.Spool.Files

    box = [
      {Queues.Spool,
       [
         name: "frames",
         label: "Waiting on the SD card for the Mac",
         step: 2,
         dir: Frames.spool_dir(),
         url: &Frames.url/1,
         index: index,
         # the newest N frames, a setting (all: no limit but the card's budget)
         max_files: &Frames.keep_last/0
       ] ++ spool},
      {Queues.Queue,
       name: "frames.write",
       label: "Write to the SD card",
       step: 1,
       run: {Frames, :write, []},
       # frames wait in memory here: a few seconds' worth, then new ones are dropped and counted
       max_items: 16,
       max_bytes: 64 * 1024 * 1024,
       timeout: 30_000}
    ]

    mac =
      if Frames.pull?() do
        [
          {Queues.Queue, name: "frames.fetch", label: "Copy to this Mac", step: 3, run: {Frames, :fetch, []}, concurrency: 2, max_items: 8, timeout: 120_000},
          {Queues.Queue, name: "frames.measure", label: "Find the stars", step: 4, run: {Frames, :measure, []}, concurrency: 2, max_items: 32, timeout: 60_000},
          Controller.Frames.Pull
        ]
      else
        []
      end

    Supervisor.init(box ++ mac, strategy: :one_for_one, max_restarts: 5, max_seconds: 30)
  end
end
