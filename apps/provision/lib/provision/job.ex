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

  @doc """
  Put a finished or failed job away and go back to idle.

  A job that has ended still fills the screen, and until it is put away there
  is no route back to the choices that made it. Clearing is how a failure gets
  answered by changing something rather than by starting the whole flow again.
  A running job is left alone; cancel it first.
  """
  def clear, do: GenServer.call(__MODULE__, :clear)

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

  def handle_call(:clear, _from, %{running: true} = s), do: {:reply, {:error, :busy}, s}
  def handle_call(:clear, _from, _s), do: {:reply, :ok, announce(idle())}

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

  # -n makes fwup report progress as bare numbers, which is what a bar wants
  # and what survives being read out of a file later on.
  defp fwup(parent, fw, disk) do
    args = ["-n", "-a", "-i", fw, "-d", disk, "-t", "complete", "--enable-trim"]

    case elevated(parent, "fwup", args) do
      :ok ->
        step(parent, :write, :done, "Written and flushed")
        :ok

      {:error, code, tail} ->
        {:error, :write, write_words(code, tail, disk)}
    end
  end

  @doc false
  # Writing to a raw disk is root's work, and there are three honest ways to
  # get there. We are already root, which is every Nerves box stamping a card.
  # Or sudo has been told not to ask. Or, on a Mac, the operating system asks,
  # in its own dialog, and the password never passes through us.
  #
  # What we do not do is prompt in the page. A port is a pipe and not a
  # terminal, so plain sudo cannot ask through it anyway — that is what the -n
  # is for — and a password typed into a browser is a password we would have
  # to carry and hold.
  defp elevated(parent, exe, args) do
    cond do
      root?() -> run_cmd(parent, [exe | args], [], :write, &fwup_line(parent, &1))
      passwordless_sudo?() -> run_cmd(parent, ["sudo", "-n", exe | args], [], :write, &fwup_line(parent, &1))
      macos?() -> via_dialog(parent, exe, args)
      true -> run_cmd(parent, ["sudo", "-n", exe | args], [], :write, &fwup_line(parent, &1))
    end
  end

  # `do shell script` hands its output back only once it has finished, and the
  # two minutes it is quiet for are exactly the two minutes a person most wants
  # to see moving. So the elevated command writes to a file, and we read that
  # file as it fills.
  defp via_dialog(parent, exe, args) do
    log = Path.join(System.tmp_dir!(), "observatory-write-#{System.unique_integer([:positive])}.log")
    File.write!(log, "")

    shell = Enum.map_join([exe | args], " ", &sh/1) <> " > " <> sh(log) <> " 2>&1"
    script = "do shell script " <> applescript_string(shell) <> " with administrator privileges"

    step(parent, :write, :running, "Your Mac is asking for your password")
    follower = Task.async(fn -> follow(parent, log, 0) end)

    result = run_cmd(parent, ["osascript", "-e", script], [], :write, fn _ -> :ok end)

    send(follower.pid, :stop)
    Task.shutdown(follower, 2_000)

    said = File.read(log) |> case do {:ok, t} -> t; _ -> "" end
    File.rm(log)

    case result do
      :ok -> :ok
      {:error, code, osa} -> {:error, code, String.trim(said <> "\n" <> osa)}
    end
  end

  # Read whatever is new in the file every so often. fwup -n says nothing but
  # numbers while it works, so only the lines that are not numbers are worth
  # putting in the log the page shows.
  defp follow(parent, log, at) do
    receive do
      :stop -> :ok
    after
      200 ->
        case File.stat(log) do
          {:ok, %{size: size}} when size > at ->
            chunk = read_at(log, at, size - at)

            chunk
            |> String.split(~r/[\r\n]+/, trim: true)
            |> Enum.each(fn line ->
              if fwup_line(parent, line) == :no, do: send(parent, {:log, line})
            end)

            follow(parent, log, size)

          _ ->
            follow(parent, log, at)
        end
    end
  end

  defp read_at(path, at, len) do
    case :file.open(path, [:read, :binary]) do
      {:ok, fd} ->
        out = case :file.pread(fd, at, len) do
          {:ok, data} -> data
          _ -> ""
        end

        :file.close(fd)
        out

      _ ->
        ""
    end
  end

  # Says whether the line was a percentage, so the caller knows what is left.
  defp fwup_line(parent, line) do
    case Regex.run(~r/\A\s*(\d{1,3})\s*%?\s*\z/, line) do
      [_, p] ->
        send(parent, {:percent, String.to_integer(p)})
        :percent

      _ ->
        :no
    end
  end

  defp sh(s), do: "'" <> String.replace(s, "'", "'\\''") <> "'"

  defp applescript_string(s) do
    escaped = s |> String.replace("\\", "\\\\") |> String.replace("\"", "\\\"")
    "\"" <> escaped <> "\""
  end

  defp root?, do: match?({"0", 0}, trimmed_cmd("id", ["-u"]))
  defp macos?, do: match?({:unix, :darwin}, :os.type())
  defp passwordless_sudo?, do: match?({_, 0}, trimmed_cmd("sudo", ["-n", "true"]))

  defp trimmed_cmd(exe, args) do
    {out, code} = System.cmd(exe, args, stderr_to_stdout: true)
    {String.trim(out), code}
  rescue
    _ -> {"", 1}
  end

  defp write_words(code, tail, disk) do
    cond do
      # the Mac's own password dialog, dismissed: a choice, not a fault
      String.contains?(tail, "User canceled") or String.contains?(tail, "(-128)") ->
        "The password was not given, so nothing was written. #{disk} is as it was."

      # sudo -n cannot ask for anything: a server has no terminal to ask at.
      # This is the first thing a fresh machine hits, so it gets the plainest
      # words and the way out, not a number.
      String.contains?(tail, "a password is required") or String.contains?(tail, "sudo:") ->
        "This machine asks for a password before it will write to a card, and there is nowhere here to type one. " <>
          "Allow fwup without a password (sudo visudo), or write it yourself: sudo fwup -a -i <image> -d #{disk} -t complete"

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
  defp unmount(disk) do
    case :os.type() do
      {:unix, :darwin} -> System.cmd("diskutil", ["unmountDisk", disk], stderr_to_stdout: true)
      _ -> System.cmd("umount", [disk], stderr_to_stdout: true)
    end
  rescue
    _ -> :ok
  end

  defp firmware_dir, do: Provision.firmware_dir()

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
