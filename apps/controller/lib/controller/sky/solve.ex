defmodule Controller.Sky.Solve do
  @moduledoc """
  Plate solving: hand it a photo of the sky, get back exactly where it points.
  One front door; where the work happens is the machine's choice.

      Solve.solve(jpeg_bytes, hint: %{ra_deg: 86.0, dec_deg: -2.0, radius_deg: 10})
      #=> {:ok, %{ra_deg: 83.8199, dec_deg: -5.3901, width_deg: 1.0, height_deg: 1.0,
      #          rotation_deg: -142.98, parity: "neg", seconds: 2.6, solver: "this machine"}}

  Where, in order:

    1. **this node**, when it has `solve-field` and its index files
       (`Controller.Sky.Solve.Local`);
    2. **another node in the cluster** that has them (a Mac joined to a box
       that has none): the photo's bytes travel over distribution with
       `:erpc`, the answer comes back the same way;
    3. **nova.astrometry.net** when an API key is configured
       (`Controller.Sky.Solve.Nova`);
    4. otherwise `{:error, :no_solver}`.

  `backend: SomeModule` (or `config :controller, :solver, backend: SomeModule`)
  puts a module with `solve(image, opts)` in front of all of that: how tests
  and a future solver (tetra3, Cedar) slot in. The same config list carries
  this machine's programs and runner (see `Controller.Sky.Solve.Local`):

      config :controller, :solver,
        solve_field: "/usr/bin/solve-field", djpeg: "/usr/bin/djpeg",
        index_config: "/data/astrometry/astrometry.cfg",
        runner: {Firmware.MuonTrapRunner, memory_mb: 300}

  Every solve runs in a task under `Controller.Sky.Solve.Tasks` with a
  deadline, so a crash, a hang or a slow solver comes back as an error tuple
  and never takes the caller (a LiveView, the photo session) with it.

  Knobs are `Controller.Sky.Solve.Local`'s (`hint:`, `scale:`, `downsample:`,
  `nsigma:`, `min_stars:`, `timeout:`, `blind_fallback:`) and travel to
  whichever node solves; paths and the runner stay behind, each node uses
  its own.

  With `sky: %{at: DateTime, site: %{lat, lon}}` (when and where the photo was
  taken), a match that lands below the horizon is `:below_horizon`: a false
  one, however good its odds.

  Errors: `:too_few_stars`, `:no_solution`, `:below_horizon`, `:timeout`, `:no_solver`, `:unsupported_image`,
  `{:remote, node, reason}`, `{:crashed, reason}`, or a backend's own reason.
  """

  alias Controller.Sky.{Astro, Photo}
  alias Controller.Sky.Solve.{Local, Nova}

  @tasks Controller.Sky.Solve.Tasks
  @default_timeout 90_000
  @nova_timeout 300_000
  # how long to wait for another node to say whether it can solve
  @probe_ms 1_500
  # opts that name paths on this machine: another node uses its own
  @local_only [
    :index_config,
    :solve_field,
    :djpeg,
    :an_pnmtofits,
    :image2xy,
    :runner,
    :backend,
    :tmp_dir
  ]

  @doc "True when nova.astrometry.net has an API key (the sky page's tree-line photo asks this)."
  defdelegate configured?, to: Nova

  @doc """
  Where a solve would run right now: `:local`, `{:node, node}`, `:nova`,
  `{:module, mod}` (configured), or nil when nothing can solve. Asks other
  nodes, so it can take up to #{@probe_ms} ms per node that is slow to answer.
  """
  def where(opts \\ []) do
    cond do
      mod = Local.opt(opts, :backend) -> {:module, mod}
      Local.available?(opts) -> :local
      n = remote_solver() -> {:node, n}
      Nova.configured?() -> :nova
      true -> nil
    end
  end

  @doc "Words for `where/1`: which machine solves."
  def where_words(:local), do: "this machine"

  def where_words({:node, n}),
    do:
      n |> to_string() |> String.split("@") |> List.last() |> String.replace_suffix(".local", "")

  def where_words(:nova), do: "nova.astrometry.net"
  def where_words({:module, mod}), do: inspect(mod)
  def where_words(nil), do: nil

  @doc """
  Solve an image (its bytes) wherever it can be solved; see the moduledoc.
  Blocks until the answer or the deadline (`timeout:` plus a few seconds).

  A file path instead of bytes is the sky page's tree-line photo, as it
  always was: straight to nova.astrometry.net.
  """
  def solve(image, opts \\ [])

  def solve(image, opts) when is_binary(image) do
    if legacy_path?(image) do
      Nova.solve(image, opts)
    else
      task = async(image, opts)

      case Task.yield(task, budget(opts) + 5_000) || Task.shutdown(task, :brutal_kill) do
        {:ok, result} -> result
        {:exit, reason} -> {:error, {:crashed, reason}}
        nil -> {:error, :timeout}
      end
    end
  end

  @doc """
  Start a solve under the task supervisor and return the `Task` at once. The
  caller receives `{ref, result}` (or `{:DOWN, ref, ...}` if it crashed), as
  with `Task.Supervisor.async_nolink/2`; it is never linked to the solve.
  """
  def async(image, opts \\ []) when is_binary(image) do
    Task.Supervisor.async_nolink(@tasks, fn -> run(image, opts) end)
  end

  @doc false
  # Called over :erpc by another node: solve here, with this node's files.
  def solve_here(image, opts), do: Local.solve(image, opts)

  # -- the choice ---------------------------------------------------------------------

  @doc """
  Solve in the calling process: no task of its own, no deadline beyond the
  solver's. For a caller that is itself a supervised worker (a plate in
  `Controller.Plates`), so that stopping the worker stops the solve and
  every OS process under it. Anything else wants `solve/2`.
  """
  def run(image, opts \\ []) when is_binary(image) do
    where = where(opts)

    # A frame from the simulated camera says where it was taken, so it needs
    # no sky and no solver (unless a solver module is set, a test's stand-in).
    if Controller.ScopeCamera.Sim.said(image) && not match?({:module, _}, where) do
      sim(image)
    else
      case where do
        {:module, mod} = w -> mod.solve(image, opts) |> tag(w)
        :local -> Local.solve(image, opts) |> tag(:local)
        {:node, n} -> remote(n, image, opts)
        :nova -> nova(image, opts)
        nil -> {:error, :no_solver}
      end
    end
    |> above_horizon(opts[:sky])
  end

  defp sim(image) do
    {ra, dec} = Controller.ScopeCamera.Sim.said(image)
    {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 0.3, height_deg: 0.17, rotation_deg: 0.0, parity: "neg", seconds: 0.0, stars: 25, solver: "simulator"}}
  end

  # A match that puts the photo below the horizon, when and where it was
  # taken, is a false one, however good its odds: the first night's plate
  # thirteen (Moon glare, a handful of stars), cleaned one way, "solved" at
  # Dec -69°, which never rises there. A couple of degrees of slack for
  # refraction and a photo's rough time.
  defp above_horizon({:ok, %{ra_deg: ra, dec_deg: dec}} = ok, %{at: %DateTime{} = at, site: %{lat: lat, lon: lon}}) do
    {alt, _} = Astro.alt_az(ra, dec, lat, Astro.lst_deg(at, lon))
    if alt < -2.0, do: {:error, :below_horizon}, else: ok
  end

  defp above_horizon(result, _), do: result

  defp remote(n, image, opts) do
    portable = Keyword.drop(opts, @local_only)

    try do
      :erpc.call(n, __MODULE__, :solve_here, [image, portable], budget(opts) + 3_000)
      |> tag({:node, n})
    catch
      :error, {:erpc, :timeout} -> {:error, :timeout}
      kind, reason -> {:error, {:remote, n, {kind, reason}}}
    end
  end

  defp nova(image, opts) do
    {low, high} = Keyword.get(opts, :scale, {0.3, 3.0})

    path =
      Path.join(
        System.tmp_dir!(),
        "observatory-nova-#{System.unique_integer([:positive])}#{Photo.extension(Photo.format(image))}"
      )

    File.write!(path, image)

    try do
      case Nova.solve(path, scale_lower: low, scale_upper: high) do
        {:ok, c} ->
          {:ok,
           %{
             ra_deg: c.ra_deg,
             dec_deg: c.dec_deg,
             width_deg: c.width && c.width / 3600,
             height_deg: c.height && c.height / 3600,
             rotation_deg: c.orientation_deg,
             parity: c.parity && to_string(c.parity),
             pixscale_arcsec: c.pixscale_arcsec
           }}
          |> tag(:nova)

        {:error, :solve_failed} ->
          {:error, :no_solution}

        {:error, e} when e in [:timeout_waiting_for_job, :timeout_solving] ->
          {:error, :timeout}

        other ->
          other
      end
    after
      File.rm(path)
    end
  end

  defp tag({:ok, sol}, where), do: {:ok, Map.put(sol, :solver, where_words(where))}
  defp tag(other, _where), do: other

  # the first node that answers "yes, I can solve"
  defp remote_solver do
    Node.list()
    |> Enum.find(fn n ->
      try do
        :erpc.call(n, Local, :available?, [], @probe_ms) == true
      catch
        _, _ -> false
      end
    end)
  end

  defp budget(opts) do
    case opts[:timeout] do
      ms when is_integer(ms) -> ms
      _ -> if where_cached_nova?(opts), do: @nova_timeout, else: @default_timeout
    end
  end

  # nova needs minutes; everything else is held to two
  defp where_cached_nova?(opts),
    do: not Local.available?(opts) and Node.list() == [] and Nova.configured?()

  # the tree-line photo hands over a temp file's path, not its bytes
  defp legacy_path?(s),
    do:
      byte_size(s) < 4096 and Photo.format(s) == :unknown and String.printable?(s) and
        File.regular?(s)
end
