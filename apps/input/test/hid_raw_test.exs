defmodule Input.HIDRawTest do
  @moduledoc """
  What a device says it is, from the top of its report descriptor: discovery
  opens joysticks and game pads (usage page 1, usage 4 or 5) and leaves
  keyboards, mice and media keys alone.
  """
  use ExUnit.Case, async: true

  # the first bytes of real descriptors: Usage Page, Usage, Collection(Application)
  test "a joystick, a game pad, a keyboard, a mouse, media keys" do
    assert Input.HIDRaw.top_usage(<<0x05, 0x01, 0x09, 0x04, 0xA1, 0x01, 0x15, 0x00>>) == {1, 4}
    assert Input.HIDRaw.top_usage(<<0x05, 0x01, 0x09, 0x05, 0xA1, 0x01>>) == {1, 5}
    assert Input.HIDRaw.top_usage(<<0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07>>) == {1, 6}
    assert Input.HIDRaw.top_usage(<<0x05, 0x01, 0x09, 0x02, 0xA1, 0x01>>) == {1, 2}
    assert Input.HIDRaw.top_usage(<<0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01>>) == {12, 1}
  end

  test "a two-byte usage page, and a descriptor cut short, still answer" do
    assert Input.HIDRaw.top_usage(<<0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01>>) == {0xFF00, 1}
    assert Input.HIDRaw.top_usage(<<0x05, 0x01>>) == {1, 0}
    assert Input.HIDRaw.top_usage(<<>>) == {0, 0}
  end

  test "a reader for a device that is not there says so instead of crashing" do
    pid = Input.HIDRaw.open("/dev/hidraw-not-there")
    assert_receive {^pid, {:data, {:eol, "E cannot open " <> _}}}, 1_000
  end

  # The SideWinder Dual Strike's own descriptor: 2 axes of 10 bits, 2 bits
  # padding, 2 vendor bits, 9 buttons, 3 padding, a 4-bit hat: 40 bits, 5
  # bytes. Read more than that per read and reports arrive glued together.
  test "a report's length comes from the descriptor's Input items" do
    dual_strike =
      <<0x05, 0x01, 0x09, 0x04, 0xA1, 0x01,
        0x75, 0x0A, 0x95, 0x02, 0x81, 0x02,
        0x75, 0x02, 0x95, 0x01, 0x81, 0x01,
        0x75, 0x01, 0x95, 0x02, 0x81, 0x02,
        0x75, 0x01, 0x95, 0x09, 0x81, 0x02,
        0x75, 0x03, 0x95, 0x01, 0x81, 0x01,
        0x75, 0x04, 0x95, 0x01, 0x81, 0x42, 0xC0>>

    assert Input.HIDRaw.report_length(dual_strike) == 5

    # with a report id: its byte comes first
    assert Input.HIDRaw.report_length(<<0x85, 0x01, 0x75, 0x08, 0x95, 0x06, 0x81, 0x02>>) == 7
    # nothing to go on
    assert Input.HIDRaw.report_length(<<>>) == 64
  end
end
