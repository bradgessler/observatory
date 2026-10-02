defmodule QueuesTest do
  @moduledoc """
  Queues never make a producer wait, run work in parallel up to a limit,
  contain failures to the item that failed, and keep the numbers that say
  which step is slow. The spool keeps files on disk within its limits,
  hands them out on lease, and survives a restart.
  """
  use ExUnit.Case, async: false

  alias Queues.Spool

  defp name, do: "test-#{System.unique_integer([:positive])}"

  defp eventually(fun, tries \\ 100) do
    cond do
      fun.() -> true
      tries == 0 -> flunk("never happened")
      true -> Process.sleep(20) && eventually(fun, tries - 1)
    end
  end

  describe "a queue" do
    test "takes work at once and does it in the background, in order" do
      n = name()
      me = self()
      start_supervised!({Queues.Queue, name: n, run: fn i -> send(me, {:did, i}) && :ok end})

      for i <- 1..5, do: assert(:ok = Queues.push(n, i))
      for i <- 1..5, do: assert_receive({:did, ^i}, 1_000)
      eventually(fn -> Queues.stats(n).counts.done == 5 end)
    end

    test "says full instead of waiting, or drops the oldest when told to" do
      n = name()
      gate = make_ref()
      start_supervised!({Queues.Queue, name: n, max_items: 2, run: fn _ -> receive(do: (^gate -> :ok)) end})

      assert :ok = Queues.push(n, :a)
      # :a is being worked on; two more fit in line, the third doesn't
      eventually(fn -> Queues.stats(n).running == 1 end)
      assert :ok = Queues.push(n, :b)
      assert :ok = Queues.push(n, :c)
      assert {:error, :full} = Queues.push(n, :d)
      assert Queues.stats(n).counts.rejected == 1

      m = name()
      start_supervised!(Supervisor.child_spec({Queues.Queue, name: m, max_items: 2, overflow: :drop_oldest, run: fn _ -> receive(do: (^gate -> :ok)) end}, id: :drop))
      Queues.pause(m, true)
      for i <- 1..3, do: assert(:ok = Queues.push(m, i))
      s = Queues.stats(m)
      assert s.depth == 2 and s.counts.dropped == 1
    end

    test "runs up to its concurrency at once, and a busy step reads busy" do
      n = name()
      start_supervised!({Queues.Queue, name: n, concurrency: 3, run: fn _ -> Process.sleep(300) && :ok end})
      for i <- 1..6, do: Queues.push(n, i)

      eventually(fn -> Queues.stats(n).running == 3 end)
      eventually(fn -> Queues.stats(n).counts.done == 6 end)
      s = Queues.stats(n)
      assert s.work_ms.p50 >= 300
      # the second three waited for the first three
      assert s.wait_ms.p95 >= 250
      assert s.busy > 0.5
    end

    test "a crash, an error or a hang is that item's failure only; retries are tried" do
      n = name()
      me = self()

      run = fn
        :boom -> raise "boom"
        :hang -> Process.sleep(:infinity)
        :bad -> {:error, :bad}
        {:flaky, ref} -> if Process.get(ref), do: :ok, else: (send(me, {:tried, ref}) && {:error, :not_yet})
        :fine -> :ok
      end

      start_supervised!({Queues.Queue, name: n, concurrency: 4, timeout: 300, run: run})
      for i <- [:boom, :hang, :bad, :fine], do: Queues.push(n, i)
      eventually(fn -> Queues.stats(n).counts.done == 1 and Queues.stats(n).counts.failed == 3 end)
      assert Queues.stats(n).last_error

      m = name()
      start_supervised!(Supervisor.child_spec({Queues.Queue, name: m, retries: 2, backoff_ms: 10, run: fn _ -> {:error, :nope} end}, id: :retry))
      Queues.push(m, :x)
      eventually(fn -> Queues.stats(m).counts.failed == 1 end)
    end

    test "pushing to a queue that isn't there is an answer, not a crash" do
      assert {:error, :no_queue} = Queues.push("nowhere", :x)
      assert Queues.room("nowhere") == 0
    end

    test "every queue's numbers reach the board, and the slow step is named" do
      n = name()
      start_supervised!({Queues.Queue, name: n, label: "Slow step", run: fn _ -> Process.sleep(200) && :ok end})
      for i <- 1..20, do: Queues.push(n, i)

      eventually(fn -> Enum.any?(Queues.board(), &(&1.name == n)) end, 200)
      Process.sleep(1_100)
      slow = Enum.find(Queues.board(), &(&1.name == n))
      assert slow.node == node()
      assert %{name: ^n} = Queues.bottleneck([slow, %{slow | name: "idle", busy: 0.0, oldest_wait_ms: 0}])
    end
  end

  describe "a spool" do
    setup do
      dir = Path.join(System.tmp_dir!(), "spool-#{System.unique_integer([:positive])}")
      on_exit(fn -> File.rm_rf(dir) end)
      %{dir: dir}
    end

    test "keeps files on disk, checksummed, and hands them out on lease until acked", %{dir: dir} do
      n = name()
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0, url: fn id -> "http://box/spool/#{id}" end})

      {:ok, a} = Spool.put(n, "001", "frame one", %{exp: 1})
      {:ok, _} = Spool.put(n, "002", "frame two")
      assert File.read!(Path.join(dir, "001")) == "frame one"
      assert a.sha256 == :crypto.hash(:sha256, "frame one") |> Base.encode16(case: :lower)

      [one] = Spool.lease(n, 1)
      assert one.id == "001" and one.url == "http://box/spool/001" and one.meta == %{exp: 1}
      [two] = Spool.lease(n, 5)
      assert two.id == "002"
      assert Spool.lease(n, 5) == []

      :ok = Spool.ack(n, "001")
      :ok = Spool.release(n, "002")
      assert [%{id: "002"}] = Spool.lease(n, 5)

      s = Queues.stats(n)
      assert s.kind == :spool and s.counts.taken == 1 and s.depth == 1
    end

    test "stays inside its budget: taken files go first, then it says full", %{dir: dir} do
      n = name()
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 30, min_free_bytes: 0})
      ten = String.duplicate("x", 10)

      for id <- ~w(1 2 3), do: assert({:ok, _} = Spool.put(n, id, ten))
      assert {:error, :full} = Spool.put(n, "4", ten)

      # the Mac takes the oldest: now it may go to make room
      [%{id: "1"}] = Spool.lease(n, 1)
      :ok = Spool.ack(n, "1")
      assert {:ok, _} = Spool.put(n, "4", ten)
      refute File.exists?(Path.join(dir, "1"))
      assert Queues.stats(n).counts.deleted == 1
    end

    test "a restart loses nothing: waiting files wait, a half-written one is thrown away", %{dir: dir} do
      n = name()
      pid = start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0})
      {:ok, _} = Spool.put(n, "a", "one")
      {:ok, _} = Spool.put(n, "b", "two")
      [%{id: "a"}] = Spool.lease(n, 1)
      :ok = Spool.ack(n, "a")
      File.write!(Path.join(dir, "c.part"), "half")

      stop_supervised!({Spool, n})
      refute Process.alive?(pid)
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0})

      assert [%{id: "b"}] = Spool.lease(n, 5)
      refute File.exists?(Path.join(dir, "c.part"))
      assert Queues.stats(n).used_bytes == 6
    end

    test "keeps the newest N: taken ones go first, then the oldest waiting; the limit can change live", %{dir: dir} do
      n = name()
      limit = :counters.new(1, [])
      :counters.put(limit, 1, 3)
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0, max_files: fn -> :counters.get(limit, 1) end})

      for id <- ~w(1 2 3), do: {:ok, _} = Spool.put(n, id, "x")
      [%{id: "1"}] = Spool.lease(n, 1)
      :ok = Spool.ack(n, "1")
      # a fourth: the taken one makes room
      {:ok, _} = Spool.put(n, "4", "x")
      refute File.exists?(Path.join(dir, "1"))
      # a fifth: nothing taken left, so the oldest waiting goes; the newest win
      {:ok, _} = Spool.put(n, "5", "x")
      refute File.exists?(Path.join(dir, "2"))
      assert Enum.map(Spool.lease(n, 5), & &1.id) |> Enum.sort() == ["3", "4"]
      assert Queues.stats(n).counts.evicted == 2

      # down to 1 while 3 and 4 are being copied: the newest stays, the limit waits for the copies
      :counters.put(limit, 1, 1)
      {:ok, _} = Spool.put(n, "6", "x")
      assert File.exists?(Path.join(dir, "6"))
      :ok = Spool.ack(n, "3")
      :ok = Spool.ack(n, "4")
      {:ok, _} = Spool.put(n, "7", "x")
      assert Path.wildcard(Path.join(dir, "[0-9]")) |> Enum.map(&Path.basename/1) == ["7"]
    end

    test "paused: nothing is handed out until it's lifted, and the files wait", %{dir: dir} do
      n = name()
      paused = :atomics.new(1, [])
      :atomics.put(paused, 1, 1)
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0, paused: fn -> :atomics.get(paused, 1) == 1 end})
      {:ok, _} = Spool.put(n, "a", "one")
      assert Spool.lease(n, 5) == []
      assert Queues.stats(n).paused
      :atomics.put(paused, 1, 0)
      assert [%{id: "a"}] = Spool.lease(n, 5)
    end

    test "a lease nobody acks runs out and the file is offered again", %{dir: dir} do
      n = name()
      start_supervised!({Spool, name: n, dir: dir, budget_bytes: 1_000_000, min_free_bytes: 0, lease_ms: 50})
      {:ok, _} = Spool.put(n, "a", "one")
      [%{id: "a"}] = Spool.lease(n, 1)
      Process.sleep(80)
      assert [%{id: "a"}] = Spool.lease(n, 1)
    end
  end
end
