defmodule Camera.ServerTest do
  @moduledoc "One camera's process: it connects, says what it's set to, changes settings, takes pictures, and ends cleanly when the camera stops answering."
  use ExUnit.Case, async: false

  setup do
    id = "sim-#{System.unique_integer([:positive])}"
    Camera.subscribe(id)
    {:ok, pid} = start_supervised({Camera.Server, id: id, transport: {Camera.Transport.Sim, []}})
    assert_receive {:camera, %{state: :ready}}, 2_000
    %{id: id, pid: pid}
  end

  test "it says what the camera is and how it's set", %{id: id} do
    st = Camera.status(id)

    assert st.model == "ILCE-6000" and st.settings.iso == 6400 and
             st.settings.quality == "RAW+JPEG"
  end

  # a simulated device is listed only on the node that runs it (Telescope.listed?/3), so it has to say
  test "the simulated a6000 says it is one, in its status and in what it broadcasts", %{id: id} do
    assert Camera.status(id).sim
    assert Camera.simulated?(Camera.status(id))
    {:ok, _} = Camera.set(id, iso: 800)
    assert_receive {:camera, %{settings: %{iso: 800}, sim: true}}, 1_000

    refute Camera.simulated?(%{id: "sony-ilce-6000", state: :ready, sim: false})
    refute Camera.simulated?(%{id: "sony-ilce-6000", state: :starting})
    refute Camera.simulated?(nil)
  end

  test "settings change on request and every page hears about it", %{id: id} do
    {:ok, st} = Camera.set(id, iso: 800, shutter: "1/60")
    assert st.settings.iso == 800 and st.settings.shutter == "1/60"
    assert_receive {:camera, %{settings: %{iso: 800}}}, 1_000
  end

  test "a picture comes back as its files, and the camera remembers it took one", %{id: id} do
    {:ok, [jpeg, _raw]} = Camera.capture(id)
    assert jpeg.format == :jpeg
    # and each file says what the camera was set to when the shutter was pressed
    assert jpeg.settings.iso == 6400 and jpeg.settings.quality == "RAW+JPEG"
    st = Camera.status(id)
    assert st.shots == 1 and length(st.last.files) == 2
  end

  test "a camera that stops answering ends its process, so the next start is clean", %{
    id: id,
    pid: pid
  } do
    ref = Process.monitor(pid)

    :sys.replace_state(pid, fn s ->
      %{s | conn: %{s.conn | state: %{s.conn.state | fail_after: 0}}}
    end)

    assert {:error, :timeout} = Camera.capture(id)
    assert_receive {:DOWN, ^ref, :process, ^pid, {:shutdown, :timeout}}, 1_000
  end
end
