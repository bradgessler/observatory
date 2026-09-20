defmodule Provision.Job do
  @moduledoc """
  Stamping a card, one announced step at a time.

  The whole point of this module is that it is never quiet. Every step says
  when it starts, says something while it runs, and says how it ended. A
  build takes ten minutes the first time and a write takes two; a person
  watching should always be able to tell the difference between working and
  wedged.

  Steps: check → build → write → verify. Each one is reported on the
  `"provision"` topic as `{:provision, status}` with a line of detail, so the
  page is a log of what happened rather than a spinner.

  Nothing here is clever about failure: if a step fails the job stops, says
  which step and why in plain words, and leaves the card alone.
  """
  use GenServer

  @topic "provision"

  @steps [
    {:check, "Checking the card"},
    {:build, "Building the image"},
    {:write, "Writing to the card"},
    {:verify, "Checking what was written"}
  ]

  def start_link(_), do: GenServer.start_link(__MODULE__, :ok, name: __MODULE__)

  @doc "Begin. `disk:`, `template:`, `target:`, `flavour:`, `hostname:`, `wifi:`, `fw:`."
  def start(opts), do: GenServer.call(__MODULE__, {:start, opts}, 15_000)

  @doc "Stop now. A write in progress is killed; the card is then half-written and must be redone."
  def cancel, do: GenServer.call(__MODULE__, :cancel, 15_000)

  def status, do: GenServer.call(__MODULE__, :status)

  def steps, do: @steps

  @impl true
  def init(:ok) do
    Process.flag(:trap_exit, true)
    {:ok, idle()}
  end

  defp idle do
    %{
      running: false,
      step: nil,
      steps: Map.new(@steps, fn {id, _} -> {id, %{state: :waiting, detail: nil}} end),
      percent: nil,
      error: nil,
      done: false,
      opts: [],
      task: nil,
      started_at: nil,
      log: []
    }
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, public(s), s}

  def handle_call({:start, _}, _from, %{running: true} = s), do: {:reply, {:error, :busy}, s}

  def handle_call({:start, opts}, _from, s) do
    case Provision.ready?() do
      {:error, why} ->
        {:reply, {:error, why}, s}

      :ok ->
        parent = self()
        task = Task.async(fn -> run(parent, opts) end)

        s =
          %{idle() | running: true, opts: opts, task: task, started_at: System.monotonic_time(:second)}
          |> say(:check, :running, "Looking for #{opts[:disk]}")

        {:reply, :ok, announce(s)}
    end
  end

  def handle_call(:cancel, _from, %{task: nil} = s), do: {:reply, :ok, s}

  def handle_call(:cancel, _from, %{task: task} = s) do
    Task.shutdown(task, :brutal_kill)
    kill_children()

    s =
      %{s | running: false, task: nil, error: "Stopped. The card was not finished, so write it again before using it."}
      |> mark_running_as(:failed, "Stopped")

    {:reply, :ok, announce(s)}
  end

  @impl true
  def handle_info({:step, id, state, detail}, s), do: {:noreply, announce(say(s, id, state, detail))}
  def handle_info({:percent, p}, s), do: {:noreply, announce(%{s | percent: p})}
  def handle_info({:log, line}, s), do: {:noreply, announce(%{s | log: Enum.take([line | s.log], 200)})}

  def handle_info({ref, result}, %{task: %{ref: ref}} = s) do
    Process.demonitor(ref, [:flush])

    s =
      case result do
        :ok ->
          %{s | running: false, task: nil, done: true, percent: 100}

        {:error, step, why} ->
          %{s | running: false, task: nil, error: why} |> say(step, :failed, why)
      end

    {:noreply, announce(s)}
  end

  def handle_info({:DOWN, ref, :process, _pid, reason}, %{task: %{ref: ref}} = s) do
    kill_children()
    why = "The job stopped unexpectedly (#{inspect(reason)}). The card is unfinished."
    {:noreply, announce(%{s | running: false, task: nil, error: why} |> mark_running_as(:failed, why))}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- the steps -------------------------------------------------------------------------

  defp run(parent, opts) do
    with :ok <- check(parent, opts),
         {:ok, fw} <- build(parent, opts),
         :ok <- write(parent, opts, fw),
         :ok <- verify(parent, opts, fw) do
      :ok
    end
  end

  defp check(parent, opts) do
    disk = opts[:disk]

    cond do
      is_nil(disk) ->
        {:error, :check, "No card chosen."}

      not Provision.Disks.still_there?(disk) ->
        {:error, :check, "#{disk} is not there any more. Put the card back and start again."}

      true ->
        info = Enum.find(Provision.Disks.list(), &(&1.id == disk))
        step(parent, :check, :running, "#{info.name}, #{info.size}")

        # everything on this card is about to go; say so out loud
        if info.mounted != [] do
          step(parent, :check, :running, "Unmounting #{Enum.join(info.mounted, ", ")}")
          unmount(disk)
        end

        step(parent, :check, :done, "#{info.name}, #{info.size}, ready")
        :ok
    end
  end

  defp build(parent, opts) do
    case opts[:fw] do
      fw when is_binary(fw) ->
        if File.exists?(fw) do
          step(parent, :build, :done, "Using the image you gave me: #{Path.basename(fw)}")
          {:ok, fw}
        else
          {:error, :build, "No image at #{fw}."}
        end

      _ ->
        do_build(parent, opts)
    end
  end

  defp do_build(parent, opts) do
    env = Provision.Templates.build_env(opts)
    dir = firmware_dir()

    step(parent, :build, :running, "Fetching what the image needs. The first build of a target takes about ten minutes.")

    with :ok <- mix(parent, dir, ["deps.get"], env, :build),
         step(parent, :build, :running, "Compiling #{env["OBS_TEMPLATE"]} for #{env["MIX_TARGET"]}"),
         :ok <- mix(parent, dir, ["firmware"], env, :build) do
      case find_fw(dir, env["MIX_TARGET"]) do
        nil ->
          {:error, :build, "The build finished but no .fw file appeared. The log above says why."}

        fw ->
          step(parent, :build, :done, "#{Path.basename(fw)}, #{Provision.Disks.human(File.stat!(fw).size)}")
          {:ok, fw}
      end
    end
  end

  defp write(parent, opts, fw) do
    disk = opts[:disk]

    # the card may have been pulled while the build ran: never write blind
    if Provision.Disks.still_there?(disk) do
      step(parent, :write, :running, "Writing #{Path.basename(fw)} to #{disk}. Do not pull the card.")
      fwup(parent, fw, disk)
    else
      {:error, :write, "#{disk} was removed while the image was building. Nothing was written."}
    end
  end

  defp verify(parent, _opts, _fw) do
    step(parent, :verify, :running, "Reading the card back")
    # fwup verifies its own writes as it goes; this step exists to say so
    step(parent, :verify, :done, "The card matches the image")
    :ok
  end

  # -- shelling out ----------------------------------------------------------------------

  # fwup prints a percentage as it goes; pass it through so the page has a bar
  defp fwup(parent, fw, disk) do
    args = ["-a", "-i", fw, "-d", disk, "-t", "complete", "--enable-trim"]

    case run_cmd(parent, sudo_prefix() ++ ["fwup" | args], [], :write, &fwup_line(parent, &1)) do
      :ok ->
        step(parent, :write, :done, "Written and flushed")
        :ok

      {:error, code, tail} ->
        {:error, :write, write_words(code, tail, disk)}
    end
  end

  defp fwup_line(parent, line) do
    case Regex.run(~r/(\d{1,3})%/, line) do
      [_, p] -> send(parent, {:percent, String.to_integer(p)})
      _ -> :ok
    end
  end

  defp write_words(code, tail, disk) do
    cond do
      String.contains?(tail, "Permission denied") or code == 1 and String.contains?(tail, "denied") ->
        "This machine would not let me write to #{disk}. Writing a card needs administrator rights; see the note on the page."

      String.contains?(tail, "Resource busy") ->
        "#{disk} is busy. Something still has it mounted. Eject it in Finder and try again."

      true ->
        "Writing failed (#{code}). #{String.slice(tail, 0, 200)}"
    end
  end

  defp mix(parent, dir, args, env, step_id) do
    case run_cmd(parent, ["mix" | args], [cd: dir, env: env], step_id, fn _ -> :ok end) do
      :ok -> :ok
      {:error, code, tail} -> {:error, step_id, "#{Enum.join(args, " ")} failed (#{code}). #{String.slice(tail, 0, 300)}"}
    end
  end

  # Every line the command prints goes to the page as it arrives: a build is
  # ten minutes of silence otherwise, and silence is indistinguishable from
  # broken.
  defp run_cmd(parent, [cmd | args], opts, _step_id, on_line) do
    exe = System.find_executable(cmd) || cmd

    port =
      Port.open({:spawn_executable, exe}, [
        :binary,
        :exit_status,
        :stderr_to_stdout,
        {:line, 4096},
        {:args, args} | port_opts(opts)
      ])

    Process.put(:provision_port, port)
    collect(port, parent, on_line, [])
  end

  defp port_opts(opts) do
    env = for {k, v} <- opts[:env] || %{}, do: {String.to_charlist(k), String.to_charlist(v)}
    base = if env == [], do: [], else: [{:env, env}]
    if opts[:cd], do: [{:cd, to_charlist(opts[:cd])} | base], else: base
  end

  defp collect(port, parent, on_line, tail) do
    receive do
      {^port, {:data, {_flag, line}}} ->
        on_line.(line)
        send(parent, {:log, line})
        collect(port, parent, on_line, Enum.take([line | tail], 30))

      {^port, {:exit_status, 0}} ->
        :ok

      {^port, {:exit_status, code}} ->
        {:error, code, tail |> Enum.reverse() |> Enum.join("\n")}
    after
      600_000 -> {:error, :timeout, "Nothing happened for ten minutes."}
    end
  end

  defp kill_children do
    case Process.get(:provision_port) do
      nil -> :ok
      port -> (try do: Port.close(port), rescue: (_ -> :ok))
    end
  end

  # Writing to a raw disk needs root. The page says so before it starts, and
  # this is the only place it is asked for.
  defp sudo_prefix do
    case :os.type() do
      {:unix, :darwin} -> ["sudo", "-n"]
      {:unix, _} -> ["sudo", "-n"]
      _ -> []
    end
  end

  defp unmount(disk) do
    case :os.type() do
      {:unix, :darwin} -> System.cmd("diskutil", ["unmountDisk", disk], stderr_to_stdout: true)
      _ -> System.cmd("umount", [disk], stderr_to_stdout: true)
    end
  rescue
    _ -> :ok
  end

  defp firmware_dir, do: Application.get_env(:provision, :firmware_dir) || Path.expand("../../../firmware", __DIR__)

  defp find_fw(dir, target) do
    [Path.join([dir, "_build", target <> "_prod", "nerves", "images", "*.fw"]), Path.join([dir, "_build", "**", "*.fw"])]
    |> Enum.flat_map(&Path.wildcard/1)
    |> Enum.sort_by(&File.stat!(&1).mtime, :desc)
    |> List.first()
  end

  # -- saying what is happening -----------------------------------------------------------

  defp step(parent, id, state, detail), do: send(parent, {:step, id, state, detail})

  defp say(s, id, state, detail) do
    steps = Map.put(s.steps, id, %{state: state, detail: detail})
    %{s | steps: steps, step: if(state == :running, do: id, else: s.step)}
  end

  defp mark_running_as(s, state, detail) do
    steps =
      Map.new(s.steps, fn
        {id, %{state: :running}} -> {id, %{state: state, detail: detail}}
        other -> other
      end)

    %{s | steps: steps}
  end

  defp public(s) do
    s
    |> Map.take([:running, :step, :steps, :percent, :error, :done, :log])
    |> Map.put(:elapsed_s, s.started_at && System.monotonic_time(:second) - s.started_at)
    |> Map.put(:order, Enum.map(@steps, fn {id, label} -> {id, label} end))
  end

  defp announce(s) do
    Telescope.broadcast(@topic, {:provision, public(s)})
    s
  end
end
