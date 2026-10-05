defmodule Controller.ListedTest do
  @moduledoc """
  A simulated device is listed only on the node that runs it
  (`Telescope.listed?/3`). On 2026-10-03 a dev Mac joined the telescope box's
  cluster, and the Mac's simulated telescope camera showed on the box, which
  had no camera of its own, as live frames ("24 stars, live"). The owner tried
  to focus on stars that were not there. Mounts already went by the rule; the
  cameras do now: a page never shows another machine's simulator, Lock On
  never steers by one, and nothing of a simulator's leaves its machine.

  There is no second node here. A status is what another machine would send
  (it says its `node` and whether it is `sim`), and the broadcasts a process
  makes are watched to see which reach other machines.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{LockOn, ScopeCamera, StillCamera}

  @box :"telescope@observatory.local"
  @mac :"observatory@mac.local"

  # the telescope camera's status as each machine reports it
  defp none(node), do: %{camera: nil, sim: false, node: node, live: false, frames: []}
  defp real(node), do: %{camera: "SVBONY SV105C · 1920×1080 raw", sim: false, node: node, live: true, frames: [frame(12)]}
  defp simulator(node), do: %{camera: "Simulated camera", sim: true, node: node, live: true, video: false, settings: %{}, frames: [frame(24)]}
  defp frame(stars), do: %{seq: 7, ok: true, at: ~U[2026-10-03 07:10:00Z], w: 960, h: 540, stars: stars, background: 20, bright: %{x: 500.0, y: 280.0, edge: false}}

  describe "the telescope camera" do
    test "of two cameras, one of them a simulator on another node, this node's list has only the real one" do
      assert ScopeCamera.listed?(real(@mac), @box)
      refute ScopeCamera.listed?(simulator(@mac), @box)
      # where it runs, the simulator is the camera
      assert ScopeCamera.listed?(simulator(@mac), @mac)
      # a status that doesn't say where it is from is this machine's own
      assert ScopeCamera.listed?(%{camera: "Simulated camera", sim: true})
    end

    test "a box with no camera says it has none, whatever the Mac is simulating" do
      assert ScopeCamera.pick(none(@box), [simulator(@mac)], @box) == none(@box)
      # a real camera on the Mac is still shown on the box, and the box's own before the Mac's simulator
      assert ScopeCamera.pick(none(@box), [real(@mac)], @box) == real(@mac)
      assert ScopeCamera.pick(real(@box), [simulator(@mac)], @box) == real(@box)
      # and the Mac still shows the box's real camera in place of its own stand-in
      assert ScopeCamera.pick(simulator(@mac), [real(@box)], @mac) == real(@box)
      assert ScopeCamera.pick(simulator(@mac), [none(@box)], @mac) == simulator(@mac)
    end

    test "a page keeps the status it has when it hears another machine's simulator" do
      assert ScopeCamera.prefer(none(@box), simulator(@mac), @box) == none(@box)
      # a real camera elsewhere is better than none here; this machine's own news always shows
      assert ScopeCamera.prefer(none(@box), real(@mac), @box) == real(@mac)
      assert ScopeCamera.prefer(none(@mac), simulator(@mac), @mac) == simulator(@mac)
      assert ScopeCamera.prefer(simulator(@mac), none(@mac), @mac) == none(@mac)
    end

    test "the Telescope Camera page never shows another machine's simulated frames", %{conn: conn} do
      {:ok, view, before} = live(conn, ~p"/cameras/telescope")
      refute before =~ "24 stars"

      send(view.pid, {:scope_camera, simulator(@mac)})
      html = render(view)
      refute html =~ "24 stars"
      refute html =~ "Live View On"
    end

    test "nothing of the simulator's is told to another machine: its status, its frames, its numbers" do
      id = "sim-listed-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(id)
      assert_receive {:mount, %{connected: true}}, 2_000

      camera = Process.whereis(ScopeCamera)
      ScopeCamera.subscribe()
      Queues.subscribe()
      on_exit(fn -> ScopeCamera.simulate(false) end)
      here = node()

      ScopeCamera.simulate(true)
      assert_receive {:scope_camera, %{sim: true, camera: "Simulated camera", node: ^here}}, 5_000
      watch(camera)
      {:ok, taken} = ScopeCamera.grab(mount: id)
      seq = taken.record.seq
      assert_receive {:scope_camera, %{sim: true, frames: [%{seq: ^seq, sim: true} | _]}}, 5_000
      # the camera as a step on the Queues page, every second
      assert_receive {:queue, ^here, "camera", _}, 5_000

      told = watched(camera)
      assert Enum.any?(told, &match?({:local_broadcast, "scope_camera", {:scope_camera, %{sim: true}}}, &1))
      assert Enum.any?(told, &match?({:local_broadcast, "queues", {:queue, _, "camera", _}}, &1))
      for {:broadcast, topic, message} <- told, do: refute(simulated?(message), "sent to every machine on #{topic}: #{inspect(message, limit: 8)}")

      # Switched off (as when a real camera takes its place): every machine is told what there is
      # now, and none of the simulator's frames go with it.
      messages()
      ScopeCamera.simulate(false)
      assert_receive {:scope_camera, %{camera: nil, sim: false, frames: []}}, 5_000
      assert [%{camera: nil, sim: false, frames: []} | _] = for({:broadcast, "scope_camera", {:scope_camera, status}} <- watched(camera), do: status)
      # they are still the simulator's when it is the camera again
      ScopeCamera.simulate(true)
      assert_receive {:scope_camera, %{sim: true, frames: [_ | _] = frames}}, 5_000
      assert Enum.any?(frames, &(&1.seq == seq))
    end
  end

  describe "Lock On" do
    setup do
      id = "sim-listed-lock-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(id)
      assert_receive {:mount, %{connected: true}}, 2_000
      LockOn.release()
      on_exit(fn -> LockOn.release() end)
      %{id: id}
    end

    test "never steers by another machine's simulated camera; this machine's frames it takes", %{id: id} do
      :ok = LockOn.start(id, source: :scope, target: :bright)
      lock = Process.whereis(LockOn)

      send(lock, {:scope_camera, simulator(@mac)})
      assert :sys.get_state(lock).last_seq == nil

      send(lock, {:scope_camera, simulator(node())})
      assert :sys.get_state(lock).last_seq == 7
    end
  end

  describe "the stills camera" do
    # the stills camera's status as each machine reports it
    defp stills(node, camera) do
      %{camera: camera, seen: [], shooting: false, interval_ms: 0, busy: false, last: nil, why: nil, solving: false, solve: nil, free_mb: 20_000, room_for: 700, node: node}
    end

    defp a6000(sim), do: %{id: if(sim, do: "sim-a6000", else: "sony-ilce-6000"), state: :ready, sim: sim, model: "ILCE-6000", settings: %{iso: 800, shutter: "1/60", quality: "RAW+JPEG"}}

    test "another node's simulated a6000 is not listed here; its real one is" do
      refute StillCamera.listed?(stills(@mac, a6000(true)), @box)
      assert StillCamera.listed?(stills(@mac, a6000(false)), @box)
      assert StillCamera.listed?(stills(@mac, a6000(true)), @mac)
      assert StillCamera.listed?(stills(@mac, nil), @box)
      # a status that doesn't say where it is from is this machine's own
      assert StillCamera.listed?(Map.delete(stills(@mac, a6000(true)), :node))
    end

    test "the Stills Camera page never shows another machine's simulated camera", %{conn: conn} do
      # no stills camera on this machine (one a test before this started may take a few seconds to go)
      eventually(fn -> StillCamera.status().camera == nil end)
      {:ok, view, html} = live(conn, ~p"/cameras/stills")
      assert html =~ "No stills camera"

      send(view.pid, {:still_camera, stills(@mac, a6000(true))})
      html = render(view)
      assert html =~ "No stills camera"
      refute html =~ "Take Picture"

      # the same camera on this machine is this page's camera
      send(view.pid, {:still_camera, stills(node(), a6000(true))})
      assert render(view) =~ "Take Picture"
    end

    test "a simulated a6000 says so from the first moment, and its news stays on this machine" do
      id = "sim-listed-#{System.unique_integer([:positive])}"
      Camera.subscribe(id)
      StillCamera.subscribe()
      page_camera = Process.whereis(StillCamera)
      watch(page_camera)

      camera = start_supervised!({Camera.Server, id: id, transport: {Camera.Transport.Sim, []}})
      assert Camera.simulated?(Camera.status(id))
      assert_receive {:camera, %{id: ^id, state: :ready, sim: true}}, 5_000
      here = node()
      assert_receive {:still_camera, %{camera: %{id: ^id, sim: true}, node: ^here}}, 5_000

      # a change of setting is news: to this machine, on both of the camera's topics
      watch(camera)
      {:ok, _} = Camera.set(id, iso: 800)
      assert_receive {:camera, %{id: ^id, settings: %{iso: 800}}}, 5_000
      assert [{:local_broadcast, "camera:" <> ^id, _}, {:local_broadcast, "cameras", _}] = watched(camera)

      told = watched(page_camera)
      assert Enum.any?(told, &match?({:local_broadcast, "still_camera", {:still_camera, %{camera: %{sim: true}}}}, &1))
      for {:broadcast, topic, message} <- told, do: refute(simulated?(message), "sent to every machine on #{topic}: #{inspect(message, limit: 8)}")
    end
  end

  # -- which broadcasts a process makes: to every node, or to this machine only -------------------

  @pubsub [:broadcast, :local_broadcast]

  defp watch(pid) do
    for name <- @pubsub, do: :erlang.trace_pattern({Phoenix.PubSub, name, 3}, true, [])
    :erlang.trace(pid, true, [:call])

    on_exit(fn ->
      if Process.alive?(pid), do: :erlang.trace(pid, false, [:call])
      for name <- @pubsub, do: :erlang.trace_pattern({Phoenix.PubSub, name, 3}, false, [])
    end)
  end

  # `[{:broadcast | :local_broadcast, topic, message}]` since the last look, in order
  defp watched(pid) do
    delivered = :erlang.trace_delivered(pid)
    assert_receive {:trace_delivered, ^pid, ^delivered}, 5_000
    traces(pid)
  end

  defp traces(pid) do
    receive do
      {:trace, ^pid, :call, {Phoenix.PubSub, name, [Telescope.PubSub, topic, message]}} -> [{name, topic, message} | traces(pid)]
    after
      0 -> []
    end
  end

  # is this news a simulated device's, or does it carry a simulated frame?
  defp simulated?({:scope_camera, status}), do: status.sim or Enum.any?(status.frames, & &1[:sim])
  defp simulated?({:queue, _node, "camera", _stats}), do: true
  defp simulated?({:still_camera, status}), do: Camera.simulated?(status.camera)
  defp simulated?({:camera, status}), do: Camera.simulated?(status)
  defp simulated?(_), do: false

  # everything waiting in this process's mailbox, taken out of it
  defp messages do
    receive do
      message -> [message | messages()]
    after
      0 -> []
    end
  end

  defp eventually(fun, tries \\ 200) do
    cond do
      fun.() -> true
      tries == 0 -> flunk("never happened")
      true -> Process.sleep(50) && eventually(fun, tries - 1)
    end
  end
end
