defmodule Controller.Sky.Solve.Runner do
  @moduledoc """
  How the plate solver runs an external command (`djpeg`, `solve-field`).
  The solver decides *what* to run; a runner decides *how*: on a Mac, a
  plain Port with a deadline (`Controller.Sky.Solve.Runner.Port`, the
  default); on a Pi, `nice -n 19` inside a memory-capped cgroup (MuonTrap),
  so a solve can never starve the mount driver or run the box out of memory.

  Plug one in per call (`runner: {MyRunner, opts}`) or for the machine:

      config :controller, :solver, runner: {Firmware.MuonTrapRunner, cgroup_path: "solver", memory_mb: 300}

  A runner's `run/3` gets the executable, its arguments and:

    * `cd:` the working directory
    * `env:` `[{name, value}]` strings to add to the environment
    * `timeout:` milliseconds; past it the command and **everything it
      started** must be gone (solve-field starts helpers of its own)
    * whatever else was in the `{module, opts}` pair

  and answers `{:ok, exit_status, output}`, `{:error, :timeout}` or
  `{:error, reason}`. Output is stdout and stderr together. If the process
  calling `run/3` dies, the command must die too.
  """

  @type result :: {:ok, non_neg_integer, binary} | {:error, :timeout} | {:error, term}
  @callback run(exe :: String.t(), args :: [String.t()], opts :: keyword) :: result

  @doc "Run through a `{module, opts}` runner (or a bare module)."
  def run({mod, runner_opts}, exe, args, opts), do: mod.run(exe, args, Keyword.merge(runner_opts, opts))
  def run(mod, exe, args, opts) when is_atom(mod), do: mod.run(exe, args, opts)
end

defmodule Controller.Sky.Solve.Runner.Port do
  @moduledoc """
  The default runner: an Erlang Port, a hard deadline, and a kill of the
  whole process tree (the command and everything it started) when the
  deadline passes or when the process that asked goes away first. Nothing
  is left running.
  """
  @behaviour Controller.Sky.Solve.Runner

  @impl true
  def run(exe, args, opts) do
    timeout = Keyword.fetch!(opts, :timeout)
    env = for {k, v} <- Keyword.get(opts, :env, []), do: {String.to_charlist(k), String.to_charlist(v)}

    port =
      Port.open({:spawn_executable, exe}, [:binary, :exit_status, :stderr_to_stdout, args: args, cd: Keyword.get(opts, :cd, File.cwd!()), env: env])

    os_pid =
      case Port.info(port, :os_pid) do
        {:os_pid, p} -> p
        _ -> nil
      end

    reaper = reaper(self(), os_pid)
    timer = Process.send_after(self(), {:runner_timeout, port}, timeout)
    result = collect(port, <<>>)
    Process.cancel_timer(timer)
    send(reaper, :done)

    case result do
      {:ok, _status, _out} = done ->
        done

      :timeout ->
        kill_tree(os_pid)
        safe_close(port)
        flush(port)
        {:error, :timeout}
    end
  end

  defp collect(port, out) do
    receive do
      {^port, {:data, data}} ->
        collect(port, out <> data)

      {^port, {:exit_status, status}} ->
        {:ok, status, out}

      {:runner_timeout, ^port} ->
        :timeout
    end
  end

  # If the process that owns the port dies (a worker shut down, an erpc
  # caller that gave up), the port closes but the command and its helpers
  # would run on: this watches the owner and kills them.
  defp reaper(owner, os_pid) do
    spawn(fn ->
      ref = Process.monitor(owner)

      receive do
        :done -> :ok
        {:DOWN, ^ref, :process, _, _} -> kill_tree(os_pid)
      end
    end)
  end

  @doc "Kill a process and every descendant (found first, then all killed at once)."
  def kill_tree(nil), do: :ok

  def kill_tree(pid) when is_integer(pid) do
    pids = [pid | descendants(pid)]
    System.cmd("kill", ["-9" | Enum.map(pids, &Integer.to_string/1)], stderr_to_stdout: true)
    :ok
  rescue
    _ -> :ok
  end

  defp descendants(pid) do
    case System.cmd("pgrep", ["-P", Integer.to_string(pid)], stderr_to_stdout: true) do
      {out, 0} ->
        kids = for word <- String.split(out), {n, ""} <- [Integer.parse(word)], do: n
        kids ++ Enum.flat_map(kids, &descendants/1)

      _ ->
        []
    end
  rescue
    _ -> []
  end

  defp safe_close(port) do
    Port.close(port)
  rescue
    _ -> :ok
  end

  defp flush(port) do
    receive do
      {^port, _} -> flush(port)
    after
      0 -> :ok
    end
  end
end
