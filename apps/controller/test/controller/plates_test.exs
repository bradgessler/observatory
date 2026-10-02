defmodule Controller.PlatesTest do
  @moduledoc """
  The plate queue with the solver stood in for by one the test drives: each
  solve says it started, waits at a gate the test opens, then answers from
  the "photo" itself. So order, concurrency, crashes, restarts and give-ups
  can be watched exactly, and nothing depends on astrometry.net.
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
    # two plates or more and the fit is there
    assert view.report.n == 4
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
