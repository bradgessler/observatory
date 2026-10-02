defmodule Controller.Test.RecordingRunner do
  @moduledoc """
  A solver runner for tests: runs each program the normal way and tells the
  test process what ran, with what, and what it said:
  `{:ran, program_name, args, result}`. Plug in with
  `runner: {Controller.Test.RecordingRunner, test_pid: self()}`.
  """
  @behaviour Controller.Sky.Solve.Runner

  @impl true
  def run(exe, args, opts) do
    result = Controller.Sky.Solve.Runner.Port.run(exe, args, opts)
    send(Keyword.fetch!(opts, :test_pid), {:ran, Path.basename(exe), args, result})
    result
  end
end
