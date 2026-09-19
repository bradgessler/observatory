defmodule Watch.History do
  @moduledoc """
  The recent past, for whoever (or whatever) is watching: every frame the
  camera grabs is written to disk under a sortable name and kept for a
  bounded window, then pruned. An agent asking "what happened during that
  slew?" reads the strip; a page shows thumbnails; a restart doesn't lose it.

  Retention is the tightest of three limits, all configurable in `:watch`:

      max_frames: 240      # ~20 min at the 5 s default interval
      max_age_s:  1_200    # 20 minutes
      max_bytes:  256 MB

  Frames live in `~/.observatory/watch/frames/<unix_ms>.jpg`. Only the index
  (name, time, size) is kept in memory; bytes are read on demand.
  """
  use GenServer
  require Logger

  @defaults %{max_frames: 240, max_age_s: 1_200, max_bytes: 256 * 1024 * 1024}

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Where frames are kept."
  def dir, do: Application.get_env(:watch, :dir) || Path.join([System.user_home!(), ".observatory", "watch", "frames"])

  @doc "Retention policy in force."
  def policy, do: Map.merge(@defaults, Map.new(Application.get_env(:watch, :history, [])))

  @doc "Record a captured frame (`%{jpeg, at, device, bytes}`). Returns its entry."
  def put(frame), do: GenServer.call(__MODULE__, {:put, frame})

  @doc "Entries newest first: `%{name, at, bytes, device}`. `limit:` caps the count, `since:` a DateTime floor."
  def list(opts \\ []), do: GenServer.call(__MODULE__, {:list, opts})

  @doc "Bytes of one frame by name (`\"1758300000000.jpg\"`)."
  def read(name) do
    with true <- valid_name?(name), {:ok, bin} <- File.read(Path.join(dir(), name)) do
      {:ok, bin}
    else
      _ -> {:error, :not_found}
    end
  end

  @doc "Count, bytes, oldest and newest — for status lines."
  def summary, do: GenServer.call(__MODULE__, :summary)

  @doc "Drop everything on disk. Used by tests and by a 'clear' button."
  def clear, do: GenServer.call(__MODULE__, :clear)

  def valid_name?(name), do: is_binary(name) and Regex.match?(~r/^\d{10,16}\.jpg$/, name)

  # -- server -----------------------------------------------------------------------

  @impl true
  def init(_) do
    File.mkdir_p!(dir())
    {:ok, %{entries: rebuild()}, {:continue, :prune}}
  end

  @impl true
  def handle_continue(:prune, s), do: {:noreply, %{s | entries: prune(s.entries)}}

  @impl true
  def handle_call({:put, %{jpeg: jpeg, at: at} = frame}, _from, s) do
    name = "#{DateTime.to_unix(at, :millisecond)}.jpg"
    entry = %{name: name, at: at, bytes: byte_size(jpeg), device: Map.get(frame, :device, "default")}

    case File.write(Path.join(dir(), name), jpeg) do
      :ok ->
        {:reply, {:ok, entry}, %{s | entries: prune([entry | s.entries])}}

      {:error, why} ->
        Logger.warning("watch history: could not write #{name}: #{inspect(why)}")
        {:reply, {:error, why}, s}
    end
  end

  def handle_call({:list, opts}, _from, s) do
    entries = s.entries
    entries = if since = opts[:since], do: Enum.take_while(entries, &(DateTime.compare(&1.at, since) != :lt)), else: entries
    entries = if limit = opts[:limit], do: Enum.take(entries, limit), else: entries
    {:reply, entries, s}
  end

  def handle_call(:summary, _from, s) do
    {:reply,
     %{
       count: length(s.entries),
       bytes: Enum.reduce(s.entries, 0, &(&1.bytes + &2)),
       newest: s.entries |> List.first() |> then(&(&1 && &1.at)),
       oldest: s.entries |> List.last() |> then(&(&1 && &1.at)),
       policy: policy()
     }, s}
  end

  def handle_call(:clear, _from, s) do
    Enum.each(s.entries, &File.rm(Path.join(dir(), &1.name)))
    {:reply, :ok, %{s | entries: []}}
  end

  # Entries are newest first. Walk them keeping a running count/size; anything
  # past a limit, or older than the window, is removed from disk.
  defp prune(entries) do
    %{max_frames: mf, max_age_s: ma, max_bytes: mb} = policy()
    cutoff = DateTime.add(DateTime.utc_now(), -ma, :second)

    {keep, drop, _, _} =
      Enum.reduce(entries, {[], [], 0, 0}, fn e, {keep, drop, n, bytes} ->
        if n < mf and bytes + e.bytes <= mb and DateTime.compare(e.at, cutoff) != :lt,
          do: {[e | keep], drop, n + 1, bytes + e.bytes},
          else: {keep, [e | drop], n, bytes}
      end)

    Enum.each(drop, &File.rm(Path.join(dir(), &1.name)))
    Enum.reverse(keep)
  end

  # Index from whatever is already on disk, so a restart keeps the past.
  defp rebuild do
    dir()
    |> Path.join("*.jpg")
    |> Path.wildcard()
    |> Enum.flat_map(fn path ->
      name = Path.basename(path)

      with true <- valid_name?(name),
           {ms, ""} <- Integer.parse(Path.rootname(name)),
           {:ok, at} <- DateTime.from_unix(ms, :millisecond),
           {:ok, %{size: size}} <- File.stat(path) do
        [%{name: name, at: at, bytes: size, device: "?"}]
      else
        _ -> []
      end
    end)
    |> Enum.sort_by(& &1.name, :desc)
  end
end
