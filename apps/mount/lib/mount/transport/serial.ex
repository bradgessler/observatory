defmodule Mount.Transport.Serial do
  @moduledoc """
  EQDIR cable: a USB UART wired straight into the HAND CONTROL port,
  9600 baud 8N1, 3.3 V TTL. The mount answers each frame within a few ms,
  so a synchronous write/read-until-CR is all we need.
  """
  @behaviour Mount.Transport

  @speed 9600
  @reply_timeout 1_000

  @impl true
  def open(opts) do
    port = Keyword.fetch!(opts, :port)

    with {:ok, uart} <- Circuits.UART.start_link(),
         :ok <- Circuits.UART.open(uart, port, speed: @speed, active: false) do
      {:ok, %{uart: uart, port: port}}
    end
  end

  @impl true
  def exchange(%{uart: uart} = state, frame) do
    Circuits.UART.flush(uart)

    case Circuits.UART.write(uart, frame) do
      :ok ->
        case read_reply(uart, "", System.monotonic_time(:millisecond) + @reply_timeout) do
          {:ok, reply} -> {:ok, reply, state}
          {:error, reason} -> {:error, reason, state}
        end

      {:error, reason} ->
        {:error, reason, state}
    end
  end

  defp read_reply(uart, acc, deadline) do
    remaining = deadline - System.monotonic_time(:millisecond)

    cond do
      String.ends_with?(acc, "\r") ->
        {:ok, acc}

      remaining <= 0 ->
        if acc == "", do: {:error, :timeout}, else: {:error, {:partial, acc}}

      true ->
        case Circuits.UART.read(uart, remaining) do
          {:ok, ""} -> read_reply(uart, acc, deadline)
          {:ok, data} -> read_reply(uart, acc <> data, deadline)
          {:error, reason} -> {:error, reason}
        end
    end
  end

  @impl true
  def close(%{uart: uart}) do
    Circuits.UART.close(uart)
    Circuits.UART.stop(uart)
  end

  @doc """
  Serial ports that look like an EQDIR cable (FTDI is what every one of them
  ships with). Returns a list of device paths.
  """
  def detect do
    Circuits.UART.enumerate()
    |> Enum.filter(fn {_name, info} -> info[:vendor_id] == 0x0403 end)
    |> Enum.map(fn {name, _} -> device_path(name) end)
    |> Enum.sort()
  end

  # enumerate/0 hands back bare names: "cu.usbserial-XXXX" on macOS, "ttyUSB0" on Linux.
  defp device_path("/" <> _ = name), do: name
  defp device_path(name), do: "/dev/" <> name
end
