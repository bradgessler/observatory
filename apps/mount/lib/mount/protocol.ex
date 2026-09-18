defmodule Mount.Protocol do
  @moduledoc """
  The Sky-Watcher motor-controller wire protocol — what talks on the mount's
  HAND CONTROL port when an EQDIR cable is plugged in instead of a SynScan.

  Frames look like `:<cmd><axis><data>\\r`; replies are `=<data>\\r` on success
  or `!<code>\\r` on error. 24-bit numbers travel as six hex digits in
  byte-reversed order (`0x123456` is sent as `"563412"`).
  """

  @sidereal_day 86164.0905
  @center 0x800000

  @type axis :: :ra | :dec | :both

  # -- framing ---------------------------------------------------------------

  @spec encode(String.t(), axis, String.t()) :: binary
  def encode(cmd, axis, data \\ "") when byte_size(cmd) == 1 do
    ":" <> cmd <> axis_char(axis) <> data <> "\r"
  end

  def axis_char(:ra), do: "1"
  def axis_char(:dec), do: "2"
  def axis_char(:both), do: "3"

  @spec decode(binary) :: {:ok, String.t()} | {:error, term}
  def decode("=" <> rest), do: {:ok, String.trim_trailing(rest, "\r")}
  def decode("!" <> rest), do: {:error, error(String.trim_trailing(rest, "\r"))}
  def decode(""), do: {:error, :no_response}
  def decode(other), do: {:error, {:garbage, other}}

  defp error("0"), do: :unknown_command
  defp error("1"), do: :bad_length
  defp error("2"), do: :motor_running
  defp error("3"), do: :bad_character
  defp error("4"), do: :not_initialized
  defp error("5"), do: :driver_sleeping
  defp error("7"), do: :pec_training
  defp error("8"), do: :no_pec_data
  defp error(code), do: {:code, code}

  # -- numbers ----------------------------------------------------------------

  @doc "Byte-reversed 24-bit hex → integer. `\"563412\"` → `0x123456`."
  def to_int(<<a::binary-2, b::binary-2, c::binary-2>>), do: String.to_integer(c <> b <> a, 16)
  def to_int(<<a::binary-2, b::binary-2>>), do: String.to_integer(b <> a, 16)
  def to_int(<<a::binary-2>>), do: String.to_integer(a, 16)

  @doc "Integer → byte-reversed 24-bit hex."
  def from_int(n) when n >= 0 and n <= 0xFFFFFF do
    <<a::binary-2, b::binary-2, c::binary-2>> =
      n |> Integer.to_string(16) |> String.pad_leading(6, "0")

    c <> b <> a
  end

  # -- positions --------------------------------------------------------------

  @doc "The step count both axes report right after power-on."
  def center, do: @center

  def steps_to_degrees(steps, steps_per_rev), do: (steps - @center) * 360 / steps_per_rev
  def degrees_to_steps(deg, steps_per_rev), do: round(deg * steps_per_rev / 360)

  # -- status ------------------------------------------------------------------

  @doc """
  Decodes the three-nibble reply to `:f`. Each hex digit is a bitfield:
  mode (bit0 slew/tracking vs goto, bit1 direction, bit2 fast), motion
  (bit0 running, bit1 blocked), init (bit0 energized).
  """
  def decode_status(<<m::8, r::8, i::8>>) do
    m = hex(m)
    r = hex(r)
    i = hex(i)

    %{
      mode: if(band(m, 1) == 1, do: :slew, else: :goto),
      direction: if(band(m, 2) == 2, do: :reverse, else: :forward),
      speed: if(band(m, 4) == 4, do: :fast, else: :slow),
      running: band(r, 1) == 1,
      blocked: band(r, 2) == 2,
      initialized: band(i, 1) == 1
    }
  end

  defp hex(c), do: String.to_integer(<<c>>, 16)
  defp band(a, b), do: Bitwise.band(a, b)

  # -- speeds -------------------------------------------------------------------

  @doc "Steps per second that keeps a star still, for an axis with `steps_per_rev`."
  def sidereal_rate(steps_per_rev), do: steps_per_rev / @sidereal_day

  @doc """
  Picks the motion mode and the timer preload (`:I` value) for a slew at
  `rate` × sidereal. Rates above 128× need the high-speed microstep mode.
  """
  def slew_params(rate, %{steps_per_rev: cpr, timer_freq: tf, high_speed_ratio: hs})
      when rate > 0 do
    fast? = rate > 128
    steps_per_s = sidereal_rate(cpr) * rate
    period = tf * if(fast?, do: hs, else: 1) / steps_per_s
    {if(fast?, do: :fast, else: :slow), max(round(period), 1)}
  end

  @doc "Actual rate (× sidereal) a given mode/period pair produces."
  def rate_for(mode, period, %{steps_per_rev: cpr, timer_freq: tf, high_speed_ratio: hs}) do
    tf * if(mode == :fast, do: hs, else: 1) / period / sidereal_rate(cpr)
  end

  @doc "`:G` motion-mode byte pair. Goto ignores fast/slow (the mount ramps)."
  def motion_mode(:goto, dir), do: "0" <> dir_char(dir)
  def motion_mode(:slow, dir), do: "1" <> dir_char(dir)
  def motion_mode(:fast, dir), do: "3" <> dir_char(dir)

  defp dir_char(:forward), do: "0"
  defp dir_char(:reverse), do: "1"
end
