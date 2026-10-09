defmodule Controller.PlatesTest do
  @moduledoc """
  The plate queue with the solver stood in for by one the test drives: each
  solve says it started, waits at a gate the test opens, then answers from
  the "photo" itself. So order, concurrency, crashes, restarts and give-ups
  can be watched exactly, and nothing depends on astrometry.net. The fit of
  the model is stood in for the same way where it is the thing under test:
  the real fit, behind a gate, that can also be told to fall over.
  """
  use ExUnit.Case, async: false

  alias Controller.Plates

  defmodule Gate do
    @moduledoc false
    def solve(image, _opts) do
      send(:persistent_term.get({__MODULE__, :test}), {:solving, image})
      wait()

      case image do
        "P5 BOOM" <> _ -> raise "the solver fell over"
        "P5 DARK" <> _ -> {:error, :too_few_stars}
        "P5 STUB " <> rest ->
          [ra, dec] = rest |> String.split() |> Enum.take(2) |> Enum.map(&String.to_float/1)
          {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 1.0, height_deg: 0.75, rotation_deg: 0.0, parity: "neg", seconds: 0.01, stars: 40}}
      end
    end

    defp wait do
      if :persistent_term.get({__MODULE__, :open}, true), do: :ok, else: (Process.sleep(10) && wait())
    end

    def open(open?), do: :persistent_term.put({__MODULE__, :open}, open?)
  end

  defmodule Fit do
    @moduledoc false
    # The real fit behind a gate of its own: it says it started (and who it
    # is), waits while the gate is shut, for ten seconds at most, as a cold
    # fit on a Pi would, then fits, or falls over when told to.
    def fit(samples, opts) do
      send(:persistent_term.get({__MODULE__, :test}), {:fitting, length(samples), self()})
      wait(System.monotonic_time(:millisecond) + 10_000)
      if :persistent_term.get({__MODULE__, :boom}, false), do: raise("the fit fell over")
      Controller.Sky.Polar.fit(samples, opts)
    end

    defp wait(until) do
      if :persistent_term.get({__MODULE__, :open}, true) or System.monotonic_time(:millisecond) >= until, do: :ok, else: (Process.sleep(10) && wait(until))
    end

    def open(open?), do: :persistent_term.put({__MODULE__, :open}, open?)
    def boom(boom?), do: :persistent_term.put({__MODULE__, :boom}, boom?)
  end

  setup do
    id = "sim-plates-#{System.unique_integer([:positive])}"
    :persistent_term.put({Gate, :test}, self())
    Gate.open(true)
    Application.put_env(:controller, :solver, backend: Gate)
    # the stub solves to Dec +45°, which a solve below the horizon would refuse at some
    # hours from the default site on the equator; near the north pole it's up all day
    old_site = Application.get_env(:controller, :site)
    Application.put_env(:controller, :site, %{lat: 89.0, lon: 0.0, name: "test pole"})
    Plates.subscribe(id)

    on_exit(fn ->
      Gate.open(true)
      if old_site, do: Application.put_env(:controller, :site, old_site), else: Application.delete_env(:controller, :site)
      Application.delete_env(:controller, :solver)
      Plates.set_workers(Plates.default_workers())
      Plates.clear(id)
    end)

    %{id: id}
  end

  defp snap(id, {r, d}, extra \\ %{}) do
    Map.merge(
      %{id: id, homed: true, homed_at: 111, connected: true, tracking: :off,
        axes: %{ra: %{degrees: r / 1, steps: 8_388_608 + round(r * 25_600), running: false, deg_per_s: 0.0, goto_pending: false},
                dec: %{degrees: d / 1, steps: 8_388_608 + round(d * 25_600), running: false, deg_per_s: 0.0, goto_pending: false}}},
      extra
    )
  end

  defp photo(tag, i), do: "P5 #{tag} #{10.0 + i} 45.0 #{i}"

  defp add(id, image, spot \\ {0, -40}, extra \\ %{}), do: Plates.add(id, image, Plates.capture(snap(id, spot, extra), report: nil))

  # wait for the broadcast view that satisfies `ok?`
  defp await(id, ok?, ms \\ 3_000) do
    receive do
      {:plates, ^id, view} -> if ok?.(view), do: view, else: await(id, ok?, ms)
    after
      ms -> flunk("the plates never got there; now: #{inspect(Plates.view(id).plates |> Enum.map(&{&1.n, &1.state, &1.reason}))}")
    end
  end

  defp states(view), do: Enum.map(view.plates, & &1.state)
  defp solving_started, do: receive(do: ({:solving, img} -> img), after: (2_000 -> flunk("no solve started")))

  test "oldest first, one at a time with one worker, and each lands as it solves", %{id: id} do
    :ok = Plates.set_workers(1)
    Gate.open(false)
    for i <- 1..4, do: assert({:ok, ^i} = add(id, photo("STUB", i), {i * 10, -40}))

    view = await(id, &(states(&1) == [:solving, :queued, :queued, :queued]))
    assert Enum.map(view.plates, & &1.ahead) == [nil, 0, 1, 2]

    Gate.open(true)
    started = for _ <- 1..4, do: solving_started()
    assert started == Enum.map(1..4, &photo("STUB", &1))
    view = await(id, &(states(&1) == [:solved, :solved, :solved, :solved]))
    assert [%{solution: %{ra_deg: 11.0, stars: 40, solver: "Controller.PlatesTest.Gate"}} | _] = view.plates
    # the fit follows the plates, in a task of its own: all four are in it when it lands
    view = await(id, &(&1.report != nil and &1.report.n == 4))
    assert Enum.all?(view.plates, &is_number(&1.residual_arcmin))
    refute view.fitting
  end

  test "never more than `workers` solving at once", %{id: id} do
    :ok = Plates.set_workers(2)
    Gate.open(false)
    for i <- 1..5, do: add(id, photo("STUB", i), {i * 10, -40})

    view = await(id, &(length(&1.plates) == 5 and Enum.count(&1.plates, fn p -> p.state == :solving end) == 2))
    assert Enum.count(view.plates, &(&1.state == :queued)) == 3
    assert Plates.status().solving == 2
    Process.sleep(100)
    assert Enum.count(Plates.view(id).plates, &(&1.state == :solving)) == 2

    Gate.open(true)
    await(id, &(length(&1.plates) == 5 and Enum.all?(&1.plates, fn p -> p.state == :solved end)))
  end

  @tag capture_log: true
  test "a solve that crashes fails its plate and nothing else", %{id: id} do
    queue = Process.whereis(Plates)
    add(id, photo("STUB", 1), {0, -40})
    add(id, photo("BOOM", 2), {20, -40})
    add(id, photo("DARK", 3), {40, -40})
    add(id, photo("STUB", 4), {60, -40})

    view = await(id, &(length(&1.plates) == 4 and Enum.all?(&1.plates, fn p -> p.state in [:solved, :failed] end)))
    assert Enum.map(view.plates, &{&1.state, &1.reason}) == [{:solved, nil}, {:failed, "crashed"}, {:failed, "too_few_stars"}, {:solved, nil}]
    assert Process.whereis(Plates) == queue
  end

  test "the encoders are the capture's: where the mount went afterwards does not matter", %{id: id} do
    cap = Plates.capture(snap(id, {12.5, -33.0}), report: nil)
    # the scope moves on to the next patch of sky before the photo's bytes arrive
    _later = snap(id, {60.0, -10.0})
    {:ok, 1} = Plates.add(id, photo("STUB", 1), cap)
    [p] = await(id, &(states(&1) == [:solved])).plates
    assert p.enc.ra_deg == 12.5 and p.enc.dec_deg == -33.0
    assert p.enc.ra_steps == 8_388_608 + 320_000
    assert p.captured_at == cap.at
  end

  test "a photo taken while slewing is kept, said so, never solved or fitted, and cannot be retried", %{id: id} do
    slewing = %{axes: %{ra: %{degrees: 0.0, running: true, deg_per_s: 3.3, goto_pending: true}, dec: %{degrees: -40.0, running: false, deg_per_s: 0.0}}}
    {:ok, 1} = add(id, photo("STUB", 1), {0, -40}, slewing)
    [p] = Plates.view(id).plates
    assert {p.state, p.reason, p.moving} == {:failed, "moving", true}
    refute_receive {:solving, _}, 200
    assert Plates.retry(id, 1) == {:error, :moving}

    # tracking is not slewing: RA runs, the plate is good
    tracking = %{tracking: :sidereal, axes: %{ra: %{degrees: 30.0, running: true, deg_per_s: 0.0042}, dec: %{degrees: -40.0, running: false, deg_per_s: 0.0}}}
    {:ok, 2} = add(id, photo("STUB", 2), {30, -40}, tracking)
    view = await(id, &(Enum.at(states(&1), 1) == :solved))
    assert Enum.at(view.plates, 1).time_from == "encoders"
  end

  test "retry queues a failed plate again; remove forgets it and its file", %{id: id} do
    {:ok, 1} = add(id, photo("DARK", 1))
    await(id, &(states(&1) == [:failed]))
    assert_received {:solving, _}
    :ok = Plates.retry(id, 1)
    assert solving_started() == photo("DARK", 1)
    await(id, &(states(&1) == [:failed]))

    view = Plates.view(id)
    file = Path.join([Controller.Plates.Store.dir(), view.session, hd(view.plates).file])
    assert File.exists?(file)
    :ok = Plates.remove(id, 1)
    assert Plates.view(id).plates == []
    refute File.exists?(file)
  end

  describe "a finder (a quick solve to check the aim before a series)" do
    defp finder(id, image, spot, opts \\ []), do: Plates.add(id, image, Plates.capture(snap(id, spot), report: nil), [finder: true] ++ opts)

    test "a solver that hangs: the finder fails as \"deadline\" at its own deadline, and the queue takes the next job", %{id: id} do
      :ok = Plates.set_workers(1)
      # nothing answers while the gate is shut: every solve hangs
      Gate.open(false)
      t0 = System.monotonic_time(:millisecond)
      {:ok, 1} = finder(id, photo("STUB", 1), {10, -40}, deadline: 300)
      {:ok, 2} = add(id, photo("STUB", 2), {20, -40})
      assert solving_started() == photo("STUB", 1)

      view = await(id, &(states(&1) == [:failed, :solving]))
      assert System.monotonic_time(:millisecond) - t0 >= 300
      assert %{reason: "deadline", finder: true, solution: nil} = hd(view.plates)
      # the worker is free again and the next plate has it
      assert solving_started() == photo("STUB", 2)
      assert Plates.status().solving == 1

      Gate.open(true)
      view = await(id, &(states(&1) == [:failed, :solved]))
      assert hd(view.plates).reason == "deadline"
      # a finder is a plate like another afterwards: it can be asked for again
      :ok = Plates.retry(id, 1)
      await(id, &(states(&1) == [:solved, :solved]))
    end

    test "goes ahead of everything queued, and of the solve that has the only worker", %{id: id} do
      :ok = Plates.set_workers(1)
      Gate.open(false)
      for i <- 1..3, do: add(id, photo("STUB", i), {i * 10, -40})
      await(id, &(states(&1) == [:solving, :queued, :queued]))
      assert solving_started() == photo("STUB", 1)

      # the keeper that was solving makes way and is queued again, first among the keepers
      {:ok, 4} = finder(id, photo("STUB", 4), {40, -40})
      view = await(id, &(states(&1) == [:queued, :queued, :queued, :solving]))
      assert Enum.map(view.plates, & &1.ahead) == [0, 1, 2, nil]
      assert solving_started() == photo("STUB", 4)
      assert Plates.status().solving == 1

      Gate.open(true)
      assert for(_ <- 1..3, do: solving_started()) == Enum.map(1..3, &photo("STUB", &1))
      await(id, &(states(&1) == [:solved, :solved, :solved, :solved]))
    end

    test "that is solved in time is a plate like any other, and its deadline passing afterwards changes nothing", %{id: id} do
      {:ok, 1} = finder(id, photo("STUB", 1), {10, -40}, deadline: 150)
      assert [%{state: :solved, finder: true, solution: %{ra_deg: 11.0}}] = await(id, &(states(&1) == [:solved])).plates
      Process.sleep(250)
      assert [%{state: :solved, reason: nil}] = Plates.view(id).plates
    end

    test "has 30 seconds unless told otherwise", %{id: id} do
      assert Plates.finder_deadline() == 30_000
      Gate.open(false)
      {:ok, 1} = finder(id, photo("STUB", 1), {10, -40})
      await(id, &(states(&1) == [:solving]))
      # well inside its 30 s: still solving
      Process.sleep(400)
      assert [%{state: :solving}] = Plates.view(id).plates
    end
  end

  test "a restart loses nothing: plates that were solving are queued again and finish", %{id: id} do
    :ok = Plates.set_workers(1)
    Gate.open(false)
    for i <- 1..3, do: add(id, photo("STUB", i), {i * 20, -40})
    await(id, &(states(&1) == [:solving, :queued, :queued]))

    old = Process.whereis(Plates)
    Process.exit(old, :kill)
    new = wait_for_new(old)
    assert new != old
    # back from disk, before anything is solved again
    assert Enum.map(Plates.view(id).plates, & &1.n) == [1, 2, 3]

    Gate.open(true)
    view = await(id, &Enum.all?(&1.plates, fn p -> p.state == :solved end), 5_000)
    assert length(view.plates) == 3
  end

  @tag capture_log: true
  test "a queue that keeps crashing gives up, the app stays up, and Restart brings it back with its plates", %{id: id} do
    {:ok, 1} = add(id, photo("STUB", 1))
    await(id, &(states(&1) == [:solved]))
    app = Process.whereis(Controller.Supervisor)

    kill_until_down(8)
    assert Plates.status() == :down
    assert Plates.view(id) == {:error, :down}
    assert Plates.add(id, photo("STUB", 2), Plates.capture(snap(id, {10, -40}))) == {:error, :down}
    assert Process.whereis(Controller.Supervisor) == app
    assert Process.whereis(Controller.Endpoint)

    assert Plates.restart() == :ok
    assert %{workers: _} = Plates.status()
    assert [%{n: 1, state: :solved}] = Plates.view(id).plates
  end

  test "a server updated in place, with no queue, starts one on Restart", %{id: id} do
    {:ok, 1} = add(id, photo("STUB", 1))
    await(id, &(states(&1) == [:solved]))
    :ok = Supervisor.terminate_child(Controller.Supervisor, Controller.Plates.Supervisor)
    :ok = Supervisor.delete_child(Controller.Supervisor, Controller.Plates.Supervisor)
    assert Plates.status() == :not_started

    assert Plates.restart() == :ok
    assert %{workers: _} = Plates.status()
    assert [%{n: 1, state: :solved}] = Plates.view(id).plates
  end

  describe "the fit" do
    setup do
      # fits left over from other tests are done before this one's are watched
      idle_fits()
      :persistent_term.put({Fit, :test}, self())
      Fit.open(true)
      Fit.boom(false)
      Application.put_env(:controller, :plate_fit, Fit)

      on_exit(fn ->
        Fit.open(true)
        Fit.boom(false)
        Application.delete_env(:controller, :plate_fit)
        Application.delete_env(:controller, :plate_fit_timeout)
      end)
    end

    test "a fit that takes ten seconds: the queue answers within 50 ms all the while, with the last model", %{id: id} do
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      await(id, &(&1.report != nil and &1.report.n == 1))
      assert_receive {:fitting, 1, _}

      Fit.open(false)
      {:ok, 2} = add(id, photo("STUB", 2), {40, -40})
      assert_receive {:fitting, 2, _}, 2_000

      for _ <- 1..5 do
        {us, status} = :timer.tc(fn -> Plates.status() end)
        assert us < 50_000, "status took #{div(us, 1000)} ms while a fit ran"
        assert %{fitting: 1} = status
        Process.sleep(20)
      end

      {us, view} = :timer.tc(fn -> Plates.view(id) end)
      assert us < 50_000, "view took #{div(us, 1000)} ms while a fit ran"
      assert view.fitting
      assert view.report.n == 1
      assert states(view) == [:solved, :solved]

      # and the queue goes on taking photos and solving them
      {us, added} = :timer.tc(fn -> add(id, photo("STUB", 3), {70, -40}) end)
      assert added == {:ok, 3}
      assert us < 50_000, "add took #{div(us, 1000)} ms while a fit ran"
      await(id, &(states(&1) == [:solved, :solved, :solved]))

      Fit.open(true)
      view = await(id, &(&1.report.n == 3))
      refute view.fitting
      assert view.fit_notice == nil
    end

    test "plates that arrive during a fit are not lost: one more fit afterwards, of all of them", %{id: id} do
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      await(id, &(&1.report != nil and &1.report.n == 1))
      assert_receive {:fitting, 1, _}

      Fit.open(false)
      {:ok, 2} = add(id, photo("STUB", 2), {30, -40})
      assert_receive {:fitting, 2, _}, 2_000

      for i <- 3..5, do: {:ok, ^i} = add(id, photo("STUB", i), {i * 15, -40})
      view = await(id, &(states(&1) == [:solved, :solved, :solved, :solved, :solved]))
      # the last model answers, and nothing else is fitted meanwhile
      assert view.report.n == 1
      assert view.fitting
      refute_receive {:fitting, _, _}, 200
      assert Plates.status().fitting == 1

      Fit.open(true)
      view = await(id, &(&1.report.n == 5))
      # one fit of all five, not one for each plate that arrived
      assert_receive {:fitting, 5, _}
      refute_receive {:fitting, _, _}, 200
      refute view.fitting
      assert Enum.all?(view.plates, &is_number(&1.residual_arcmin))
      assert Plates.status().fitting == 0
    end

    test "one fit at a time: a second telescope's waits its turn", %{id: id} do
      other = id <> "-b"
      Plates.subscribe(other)
      on_exit(fn -> Plates.clear(other) end)

      Fit.open(false)
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      assert_receive {:fitting, 1, _}, 2_000
      {:ok, 1} = add(other, photo("STUB", 2), {40, -40})
      await(other, &(states(&1) == [:solved]))

      refute_receive {:fitting, _, _}, 200
      assert %{fitting: 2} = Plates.status()
      assert %{fitting: true, report: nil} = Plates.view(other)

      Fit.open(true)
      assert_receive {:fitting, 1, _}, 2_000
      await(id, &(&1.report != nil))
      await(other, &(&1.report != nil))
      assert %{fitting: 0} = Plates.status()
    end

    @tag capture_log: true
    test "a fit that raises is dropped: the queue lives, the last model stays, and one line says so", %{id: id} do
      queue = Process.whereis(Plates)
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      view = await(id, &(&1.report != nil and &1.report.n == 1))
      assert view.fit_notice == nil

      Fit.boom(true)
      {:ok, 2} = add(id, photo("STUB", 2), {40, -40})
      view = await(id, &(&1.fit_notice != nil))
      assert view.fit_notice == "The fit failed. The last model is in use."
      assert view.report.n == 1
      assert states(view) == [:solved, :solved]
      refute view.fitting
      assert Process.whereis(Plates) == queue
      assert %{fitting: 0} = Plates.status()

      # the next plate is fitted with the two before it, and the line goes
      Fit.boom(false)
      {:ok, 3} = add(id, photo("STUB", 3), {70, -40})
      view = await(id, &(&1.report.n == 3))
      assert view.fit_notice == nil
    end

    @tag capture_log: true
    test "a first fit that raises: no model, and the line says that", %{id: id} do
      Fit.boom(true)
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      view = await(id, &(&1.fit_notice != nil))
      assert view.fit_notice == "The fit failed. There is no model yet."
      assert view.report == nil
      assert states(view) == [:solved]
    end

    @tag capture_log: true
    test "a fit past its deadline is stopped and dropped the same way", %{id: id} do
      queue = Process.whereis(Plates)
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      await(id, &(&1.report != nil and &1.report.n == 1))

      Application.put_env(:controller, :plate_fit_timeout, 150)
      Fit.open(false)
      {:ok, 2} = add(id, photo("STUB", 2), {40, -40})
      assert_receive {:fitting, 2, fit}, 2_000
      watch = Process.monitor(fit)

      view = await(id, &(&1.fit_notice != nil))
      assert view.fit_notice == "The fit took too long and was stopped. The last model is in use."
      assert view.report.n == 1
      refute view.fitting
      assert_receive {:DOWN, ^watch, :process, _, :killed}
      assert Process.whereis(Plates) == queue
      assert %{fitting: 0} = Plates.status()
      # it is not tried again by itself
      refute_receive {:fitting, 2, _}, 300

      # the next thing done with the photos asks again (here one that won't solve): this time it lands
      Application.delete_env(:controller, :plate_fit_timeout)
      Fit.open(true)
      {:ok, 3} = add(id, photo("DARK", 3), {70, -40})
      assert_receive {:fitting, 2, _}, 2_000
      view = await(id, &(&1.report.n == 2))
      assert view.fit_notice == nil
    end

    test "a fit under way when the photos are started over is stopped: its model never shows", %{id: id} do
      {:ok, 1} = add(id, photo("STUB", 1), {10, -40})
      await(id, &(&1.report != nil and &1.report.n == 1))

      Fit.open(false)
      {:ok, 2} = add(id, photo("STUB", 2), {40, -40})
      assert_receive {:fitting, 2, fit}, 2_000
      watch = Process.monitor(fit)

      :ok = Plates.clear(id)
      assert %{plates: [], report: nil, fitting: false, fit_notice: nil} = Plates.view(id)
      assert_receive {:DOWN, ^watch, :process, _, :killed}

      # everything said before the start over is read; nothing after it carries a model
      drain(id)
      Fit.open(true)
      refute_receive {:plates, ^id, %{report: %{}}}, 300
      assert %{fitting: 0} = Plates.status()
    end
  end

  defp drain(id), do: receive(do: ({:plates, ^id, _} -> drain(id)), after: (0 -> :ok))

  # no fit running or waiting, for any mount
  defp idle_fits(tries \\ 200) do
    case Plates.status() do
      %{fitting: 0} -> :ok
      _ when tries > 0 -> Process.sleep(25) && idle_fits(tries - 1)
      _ -> flunk("fits from earlier tests never finished")
    end
  end

  defp wait_for_new(old, tries \\ 100) do
    case Process.whereis(Plates) do
      pid when is_pid(pid) and pid != old -> pid
      _ when tries > 0 -> Process.sleep(10) && wait_for_new(old, tries - 1)
      _ -> flunk("the queue never came back")
    end
  end

  defp kill_until_down(0), do: flunk("the plates supervisor never gave up")

  defp kill_until_down(n) do
    case Process.whereis(Plates) do
      nil ->
        # between a crash and its restart, or given up: look again in a moment
        Process.sleep(50)
        if Process.whereis(Controller.Plates.Supervisor), do: kill_until_down(n), else: :ok

      pid ->
        Process.exit(pid, :kill)
        Process.sleep(30)
        kill_until_down(n - 1)
    end
  end
end
