defmodule Camera.ClockTest do
  @moduledoc """
  The camera's own clock. The a6000's was never set (its pictures say 1 January 2014) and it offers
  no way to set it over PTP: nothing is sent to it, and its status says so. A camera that does offer
  PTP's DateTime gets this machine's time, once a connection, and only once this machine's clock is
  to be trusted. (Not tried against a real camera: the box was offline when this was written.)
  """
  use ExUnit.Case, async: false

  alias Camera.Sony

  setup do
    on_exit(fn -> Application.delete_env(:camera, :clock) end)
    :ok
  end

  defp start(opts) do
    id = "sim-clock-#{System.unique_integer([:positive])}"
    Camera.subscribe(id)
    {:ok, pid} = start_supervised({Camera.Server, id: id, transport: {Camera.Transport.Sim, opts}})
    assert_receive {:camera, %{state: :ready}}, 2_000
    {id, pid}
  end

  test "the a6000 lists no DateTime to set: nothing is sent, its pictures keep its own date, and it says why" do
    Application.put_env(:camera, :clock, fn -> ~U[2026-10-18 03:21:39Z] end)
    {id, _pid} = start([])
    st = Camera.status(id)
    assert st.clock == %{set: false, why: :not_offered}
    # what it reports about itself: firmware 2.0; a serial of zeros is no serial
    assert st.firmware == "2.0" and st.serial == nil
    {:ok, [jpeg | _]} = Camera.capture(id)
    assert jpeg.info.capture_date =~ ~r/\A20140101T08/
  end

  test "a camera that offers DateTime is set to this machine's time in UTC, and its pictures then say so" do
    Application.put_env(:camera, :clock, fn -> ~U[2026-10-18 03:21:39Z] end)
    {id, pid} = start(clock: :settable)
    assert %{set: true, sent: "20261018T032139", how: :sony, zone: "UTC"} = Camera.status(id).clock
    assert :sys.get_state(pid).conn.state.props[0x5011].current == "20261018T032139"
    {:ok, [jpeg | _]} = Camera.capture(id)
    t = Sony.parse_clock(jpeg.info.capture_date)
    assert abs(DateTime.diff(t, ~U[2026-10-18 03:21:39Z])) <= 2
  end

  test "this machine's clock not yet set: nothing is sent until it is, then it is set" do
    Application.put_env(:camera, :clock, fn -> nil end)
    {id, pid} = start(clock: :settable)
    assert Camera.status(id).clock == nil
    assert :sys.get_state(pid).conn.state.props[0x5011].current == "20140101T080202"

    # the network's time arrives; the next refresh sets it
    Application.put_env(:camera, :clock, fn -> ~U[2026-10-18 03:21:39Z] end)
    send(pid, :refresh)
    assert_receive {:camera, %{clock: %{set: true}}}, 2_000
  end

  test "a camera that refuses is asked once, and carries on taking pictures" do
    Application.put_env(:camera, :clock, fn -> ~U[2026-10-18 03:21:39Z] end)
    {id, pid} = start(clock: :refuses)
    assert %{set: false, why: {:refused, :general_error}} = Camera.status(id).clock
    send(pid, :refresh)
    Process.sleep(50)
    assert %{set: false} = Camera.status(id).clock
    assert {:ok, [_ | _]} = Camera.capture(id)
  end

  test "PTP's DateTime string, both ways" do
    assert Sony.clock_string(~U[2026-10-18 03:21:39.715Z]) == "20261018T032139"
    assert Sony.parse_clock("20140101T080202") == ~U[2014-01-01 08:02:02Z]
    assert Sony.parse_clock("20140101T080202.0+0100") == ~U[2014-01-01 08:02:02Z]
    assert Sony.parse_clock("") == nil and Sony.parse_clock(nil) == nil
  end
end
