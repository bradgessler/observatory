defmodule Firmware.Power do
  @moduledoc """
  Whether the Pi has been short of power, and how long it has been up.

  A Pi on a supply that sags (a mount's motors starting on a shared battery,
  a thin USB lead) browns out: the Wi-Fi drops or the whole board resets, and
  from a phone that looks exactly like the software falling over. The Pi's
  firmware keeps flags for it; this reads them so the Network page can say so
  in one line instead of leaving it to be guessed.

  Bits of `get_throttled`: 0 under-voltage now, 2 throttled now, 16
  under-voltage since boot, 18 throttled since boot.
  """
  import Bitwise

  @throttled "/sys/devices/platform/soc/soc:firmware/get_throttled"

  @doc "`%{undervoltage_now:, undervoltage_since_boot:, throttled_since_boot:}`, or `:unknown`."
  def status do
    with {:ok, text} <- File.read(@throttled),
         {bits, _} <- Integer.parse(String.trim(text), 16) do
      %{
        undervoltage_now: (bits &&& 0x1) != 0,
        undervoltage_since_boot: (bits &&& 0x10000) != 0,
        throttled_since_boot: (bits &&& 0x40000) != 0
      }
    else
      _ -> :unknown
    end
  end

  @doc "Seconds since this boot. A short one after a drop means the board reset."
  def uptime_s, do: :erlang.statistics(:wall_clock) |> elem(0) |> div(1000)
end
