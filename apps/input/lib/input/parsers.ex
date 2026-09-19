defmodule Input.Parsers do
  @moduledoc """
  Raw HID input report → `%{axes: [-1..1], buttons: [bool], hat: {x, y} | nil, raw: binary}`.

  A parser per device we know; the generic one shows bytes so an unknown pad
  can be mapped by looking at what changes when you press things.
  """

  @doc "Pick a parser module for a device."
  def for(%{vendor_id: 0x045E, product_id: 0x0028}), do: Input.Parsers.DualStrike
  def for(_), do: Input.Parsers.Generic

  defmodule DualStrike do
    @moduledoc """
    Microsoft SideWinder Dual Strike (1999). From its report descriptor, one
    5-byte report, no report id, little-endian bit stream:

        bits  0..9   X   signed 10-bit (-512..511)   the ball, left/right
        bits 10..19  Y   signed 10-bit               the ball, forward/back
        bits 20..21  padding
        bits 22..23  vendor bits (shift keys?)
        bits 24..32  buttons 1..9
        bits 33..35  padding
        bits 36..39  hat 0..7 clockwise from up, 8+ = centred
    """
    @behaviour Input.Parser

    @impl true
    def name, do: "SideWinder Dual Strike"

    @impl true
    def parse(<<_::binary-size(5)>> = report) do
      <<bits::little-unsigned-40>> = report
      x = sign10(Bitwise.band(bits, 0x3FF))
      y = sign10(Bitwise.band(Bitwise.bsr(bits, 10), 0x3FF))
      vendor = Bitwise.band(Bitwise.bsr(bits, 22), 0x3)
      buttons = for i <- 0..8, do: Bitwise.band(Bitwise.bsr(bits, 24 + i), 1) == 1
      hat = Bitwise.band(Bitwise.bsr(bits, 36), 0xF)

      %{
        axes: [x / 512, y / 512],
        buttons: buttons,
        hat: hat_xy(hat),
        extra: %{vendor_bits: vendor},
        raw: report
      }
    end

    def parse(other), do: Input.Parsers.Generic.parse(other)

    defp sign10(v) when v >= 512, do: v - 1024
    defp sign10(v), do: v

    defp hat_xy(0), do: {0, 1}
    defp hat_xy(1), do: {1, 1}
    defp hat_xy(2), do: {1, 0}
    defp hat_xy(3), do: {1, -1}
    defp hat_xy(4), do: {0, -1}
    defp hat_xy(5), do: {-1, -1}
    defp hat_xy(6), do: {-1, 0}
    defp hat_xy(7), do: {-1, 1}
    defp hat_xy(_), do: nil
  end

  defmodule Generic do
    @moduledoc "Unknown device: no axes or buttons, just the bytes, so a human can map it."
    @behaviour Input.Parser

    @impl true
    def name, do: "unknown HID device"

    @impl true
    def parse(report), do: %{axes: [], buttons: [], hat: nil, extra: %{}, raw: report}
  end
end

defmodule Input.Parser do
  @moduledoc "Behaviour for report parsers."
  @callback name() :: String.t()
  @callback parse(binary) :: %{axes: [float], buttons: [boolean], hat: {integer, integer} | nil, extra: map, raw: binary}
end
