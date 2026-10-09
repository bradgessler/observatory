defmodule Provision.Terminal do
  @moduledoc """
  A real shell, in a real pseudo-terminal, for the page to type into.

  Writing a card needs root, and the honest way to become root is sudo in a
  terminal: it asks, you answer, it keeps nothing. An Erlang port is a pipe and
  not a terminal, so sudo cannot ask through one. script(1) sits in between: it
  opens a pseudo-terminal, runs the shell inside it, and relays the bytes both
  ways over its own stdin and stdout, which is a pipe a port can hold.

  One shell, shared. Every page watching sees the same screen, the way every
  page sees the same telescope. Output is broadcast on `"provision:terminal"`
  and the last 64 KB is kept, so a page that opens late is shown what came
  before it. Who may type is the page's decision, not this module's.
  """
  use GenServer

  @topic "provision:terminal"
  @keep 65_536

  def start_link(_), do: GenServer.start_link(__MODULE__, :ok, name: __MODULE__)

  @doc "`{:terminal, :output, bytes}` as the shell writes, `{:terminal, :exit, status}` when it ends."
  def subscribe, do: Telescope.subscribe(@topic)

  @doc "Start a shell if none is running, `cols` wide and `rows` tall. Returns `:ok` either way."
  def open(cols \\ 100, rows \\ 30), do: GenServer.call(__MODULE__, {:open, cols, rows})

  @doc "Bytes from a person: keystrokes, a pasted line, a Ctrl-C (`\"\\x03\"`)."
  def input(data) when is_binary(data), do: GenServer.cast(__MODULE__, {:input, data})

  @doc """
  Put a command at the prompt without running it, so the person reads it and
  presses Enter themselves. Whatever was half-typed there is cleared first.
  """
  def type(line), do: input("\x15" <> line)

  @doc "Run a command line: clear whatever was half-typed, type it, press Enter."
  def run(line), do: input("\x15" <> line <> "\r")

  @doc """
  Whether the shell is sitting at its prompt with nothing running. A stamp is
  only started from idle: typed into a running one it could reach fwup and
  interrupt a write.
  """
  def idle?, do: GenServer.call(__MODULE__, :idle?)

  @doc "What is still on the screen, for a page that has just opened."
  def scrollback, do: GenServer.call(__MODULE__, :scrollback)

  def running?, do: GenServer.call(__MODULE__, :running?)

  @doc """
  Whether pages open on other devices (a phone on the same Wi-Fi) may type
  into the shell. Off until someone at the machine turns it on, and off again
  whenever this process restarts: a shell running as you is not something to
  leave open to a network by default. Enforcing who may flip it is the page's
  job; this only remembers the answer and tells every page.
  """
  def allow_lan?, do: GenServer.call(__MODULE__, :allow_lan?)
  def allow_lan(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:allow_lan, on?})

  @doc "Where the shell starts: the saved stamps, so `ls` shows them."
  def home, do: Provision.Scripts.dir()

  @impl true
  def init(:ok) do
    Process.flag(:trap_exit, true)
    {:ok, %{port: nil, buffer: "", allow_lan: false, ready: false, queued: []}}
  end

  @impl true
  def handle_call({:open, _, _}, _from, %{port: port} = s) when port != nil, do: {:reply, :ok, s}

  def handle_call({:open, cols, rows}, _from, s) do
    File.mkdir_p!(home())

    case System.find_executable("script") do
      nil ->
        {:reply, {:error, "script(1) is not on this machine, so there is no terminal to give."}, s}

      exe ->
        port =
          Port.open({:spawn_executable, exe}, [
            :binary,
            :exit_status,
            :stderr_to_stdout,
            {:cd, to_charlist(home())},
            {:env, env()},
            {:args, script_args(shell(cols, rows))}
          ])

        # If the prompt never shows (a strange PS1), send what is waiting anyway.
        Process.send_after(self(), :ready_anyway, 3_000)
        {:reply, :ok, %{s | port: port, ready: false, queued: []}}
    end
  end

  def handle_call(:scrollback, _from, s), do: {:reply, s.buffer, s}
  def handle_call(:running?, _from, s), do: {:reply, s.port != nil, s}

  # bash's prompt ends in "$ "; a running command's last output almost never does
  def handle_call(:idle?, _from, s), do: {:reply, s.port != nil and String.ends_with?(s.buffer, "$ "), s}
  def handle_call(:allow_lan?, _from, s), do: {:reply, s.allow_lan, s}

  def handle_call({:allow_lan, on?}, _from, s) do
    Telescope.broadcast(@topic, {:terminal, :allow_lan, on?})
    {:reply, :ok, %{s | allow_lan: on?}}
  end

  # Input that arrives before the shell has drawn its first prompt waits for it.
  # Typed into a terminal whose shell is still starting, a command is echoed
  # once by the terminal and drawn again by the shell, and on a narrow phone the
  # two wrap into each other: correct underneath, broken to look at.
  @impl true
  def handle_cast({:input, data}, %{port: port, ready: false} = s) when port != nil,
    do: {:noreply, %{s | queued: [data | s.queued]}}

  def handle_cast({:input, data}, %{port: port} = s) when port != nil do
    Port.command(port, data)
    {:noreply, s}
  end

  def handle_cast({:input, _}, s), do: {:noreply, s}

  @impl true
  def handle_info({port, {:data, data}}, %{port: port} = s) do
    Telescope.broadcast(@topic, {:terminal, :output, data})
    s = %{s | buffer: keep(s.buffer <> data)}
    {:noreply, if(not s.ready and String.contains?(data, "$ "), do: flush(s), else: s)}
  end

  def handle_info(:ready_anyway, %{ready: false, port: port} = s) when port != nil, do: {:noreply, flush(s)}
  def handle_info(:ready_anyway, s), do: {:noreply, s}

  def handle_info({port, {:exit_status, status}}, %{port: port} = s) do
    note = "\r\n[the shell has closed. Type anything to start a new one.]\r\n"
    Telescope.broadcast(@topic, {:terminal, :output, note})
    Telescope.broadcast(@topic, {:terminal, :exit, status})
    {:noreply, %{s | port: nil, buffer: keep(s.buffer <> note)}}
  end

  def handle_info(_, s), do: {:noreply, s}

  @impl true
  # a restart must not leave a root shell running with nobody watching it
  def terminate(_, %{port: port}) when port != nil, do: Port.close(port)
  def terminate(_, _), do: :ok

  # The size has to be set inside the terminal: from out here there is no
  # handle on the pseudo-terminal to resize. bash without its dotfiles, so a
  # prompt theme cannot fill the screen with escape codes nobody asked for.
  defp shell(cols, rows) do
    "stty cols #{cols} rows #{rows} 2>/dev/null; exec bash --noprofile --norc -i"
  end

  # script(1) takes its arguments in a different order on each system.
  defp script_args(cmd) do
    case :os.type() do
      {:unix, :darwin} -> ["-q", "/dev/null", "/bin/sh", "-c", cmd]
      _ -> ["-qfec", cmd, "/dev/null"]
    end
  end

  defp env do
    [
      {~c"TERM", ~c"xterm-256color"},
      {~c"PS1", ~c"\\W $ "},
      # macOS's bash announces that zsh is the default on every start
      {~c"BASH_SILENCE_DEPRECATION_WARNING", ~c"1"}
    ]
  end

  defp flush(s) do
    s.queued |> Enum.reverse() |> Enum.each(&Port.command(s.port, &1))
    %{s | ready: true, queued: []}
  end

  defp keep(buffer) when byte_size(buffer) > @keep,
    do: binary_part(buffer, byte_size(buffer) - @keep, @keep)

  defp keep(buffer), do: buffer
end
