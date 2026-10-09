defmodule Telescope.EventsTest do
  @moduledoc """
  A box that resets mid-slew must come back up showing what led to it: events
  written to the file as they happen are there after a restart.
  """
  use ExUnit.Case, async: false

  setup do
    path = Path.join(System.tmp_dir!(), "events-#{System.unique_integer([:positive])}.log")
    Application.put_env(:telescope, :events_file, path)

    on_exit(fn ->
      Application.delete_env(:telescope, :events_file)
      File.rm(path)
    end)

    %{path: path}
  end

  defp event(name, data), do: %{at: DateTime.utc_now(), node: node(), module: :mount, name: name, by: "test", data: data}

  test "events survive a restart, oldest to newest as they were", %{path: path} do
    {:ok, a} = GenServer.start(Telescope.Events, [])
    GenServer.cast(a, {:emit, event(:slew, %{axis: :ra, rate: 800.0})})
    GenServer.cast(a, {:emit, event(:stop, %{axis: :ra})})
    # the cast has been handled once a call returns
    assert [%{name: :stop}, %{name: :slew}] = GenServer.call(a, {:recent, 10, nil})

    # the process dies without a word, as it would when the board resets
    Process.exit(a, :kill)
    assert File.exists?(path)

    {:ok, b} = GenServer.start(Telescope.Events, [])
    assert [%{name: :stop}, %{name: :slew, data: %{axis: :ra, rate: 800.0}}] = GenServer.call(b, {:recent, 10, nil})
    GenServer.stop(b)
  end

  test "a damaged line is skipped, not fatal", %{path: path} do
    {:ok, a} = GenServer.start(Telescope.Events, [])
    GenServer.cast(a, {:emit, event(:connected, %{})})
    _ = GenServer.call(a, {:recent, 1, nil})
    GenServer.stop(a)

    # a reset mid-write leaves half a line
    File.write!(path, "bm90IGEgdGVybQ\n", [:append])

    {:ok, b} = GenServer.start(Telescope.Events, [])
    assert [%{name: :connected}] = GenServer.call(b, {:recent, 10, nil})
    GenServer.stop(b)
  end

  test "without a file configured, nothing is written" do
    Application.delete_env(:telescope, :events_file)
    {:ok, a} = GenServer.start(Telescope.Events, [])
    GenServer.cast(a, {:emit, event(:slew, %{})})
    assert [%{name: :slew}] = GenServer.call(a, {:recent, 10, nil})
    GenServer.stop(a)
  end
end
