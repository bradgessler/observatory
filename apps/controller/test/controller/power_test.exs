defmodule Controller.PowerTest do
  @moduledoc "The box's supply: a dip in the Pi's own under-voltage alarm is counted, timed, and said in one line."
  use ExUnit.Case, async: false

  alias Controller.Power

  test "a dip is counted and said; when the supply recovers the line stays, saying when" do
    alarm = Path.join(System.tmp_dir!(), "in0_lcrit_alarm-#{System.unique_integer([:positive])}")
    File.write!(alarm, "0\n")
    start_supervised!({Power, name: :test_power, alarm: alarm})
    assert %{monitored: true, low: false, dips: 0} = Power.status(:test_power)
    assert Power.words(Power.status(:test_power)) == nil

    File.write!(alarm, "1\n")
    Process.sleep(1_300)
    assert %{low: true, dips: 1} = Power.status(:test_power)
    assert Power.words(Power.status(:test_power)) =~ "low right now"

    File.write!(alarm, "0\n")
    Process.sleep(1_300)
    assert %{low: false, dips: 1} = Power.status(:test_power)
    assert Power.words(Power.status(:test_power)) =~ "dipped 1 time"
  end

  test "nothing to read (a Mac): nothing said" do
    assert Power.words(%{monitored: false, low: false, dips: 0, last_dip_at: nil}) == nil
  end
end
