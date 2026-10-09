defmodule Controller.Recovery do
  @moduledoc """
  The box's own record of coming back: each boot, and each time something
  that was running is picked up again (Lock On finding its target after a
  restart). One JSON line per event in `recoveries.jsonl`, kept on the box's
  data partition, so a crash or a power cut nobody watched is still measured.

      Recovery.note(:boot, %{firmware: "940a1f73"})
      Recovery.note(:lock_resumed, %{down_s: 126.0, moved: [0.408, -0.158]})
      Recovery.recent(20)

  Every line carries the time (and whether the clock was the network's when
  it was written: a line stamped by an unset clock says so), and the seconds
  since the kernel booted, which need no clock at all. Read at
  `/recoveries.json`. Never raises: a record that can't be written is a
  logged warning, not a second failure.
  """
  require Logger

  alias Controller.Clock

  @doc "Where the record is kept (`config :controller, :recovery_log`, else `~/.observatory/recoveries.jsonl`)."
  def path, do: Application.get_env(:controller, :recovery_log, Path.join([System.user_home!(), ".observatory", "recoveries.jsonl"]))

  @doc "Write one event."
  def note(event, data \\ %{}) do
    line =
      Jason.encode!(%{
        at: DateTime.utc_now() |> DateTime.to_iso8601(),
        clock: if(Clock.synced?(), do: "network", else: "not set"),
        up_s: uptime(),
        event: to_string(event),
        data: data
      })

    File.mkdir_p!(Path.dirname(path()))
    File.write!(path(), [line, "\n"], [:append])
    :ok
  rescue
    e ->
      Logger.warning("recovery: not written: #{Exception.message(e)}")
      :ok
  end

  @doc "This boot, once: the firmware and how long the kernel had been up when the app started."
  def boot do
    unless :persistent_term.get({__MODULE__, :booted}, false) do
      :persistent_term.put({__MODULE__, :booted}, true)
      note(:boot, %{firmware: firmware(), node: to_string(node())})
    end

    :ok
  end

  @doc "The last `n` events, oldest first."
  def recent(n \\ 50) do
    case File.read(path()) do
      {:ok, body} -> body |> String.split("\n", trim: true) |> Enum.take(-n) |> Enum.flat_map(&decode/1)
      _ -> []
    end
  end

  @doc "Seconds since the kernel booted (no clock needed), or nil off Linux."
  def uptime do
    with {:ok, body} <- File.read("/proc/uptime"), [s | _] <- String.split(body), {f, _} <- Float.parse(s), do: f, else: (_ -> nil)
  end

  defp decode(line) do
    case Jason.decode(line) do
      {:ok, m} -> [m]
      _ -> []
    end
  end

  defp firmware do
    if Code.ensure_loaded?(Nerves.Runtime.KV), do: apply(Nerves.Runtime.KV, :get_active, ["nerves_fw_uuid"])
  rescue
    _ -> nil
  end
end
