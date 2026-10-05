defmodule Camera.Transport.Usb do
  @moduledoc """
  A real camera, through `priv/usbport` (C; the kernel's usbfs on Linux,
  libusb on macOS). The helper claims the camera's still-image interface and
  then moves one USB transfer per request; nothing in it knows PTP.

  Requests and replies are `{:packet, 4}` frames: `W`rite, `R`ead, `I`nterrupt
  read, `C`lear a stalled endpoint (see `c_src/usbport.c`). Every call is
  bounded: a camera that stops answering is a timeout, never a hang.
  """
  @behaviour Camera.Transport

  @doc "The helper program, or nil when this machine couldn't build it."
  def executable do
    path = Path.join(:code.priv_dir(:camera), "usbport")
    if File.exists?(path), do: path
  end

  @impl true
  def open(opts) do
    device = Keyword.fetch!(opts, :device)

    with exe when is_binary(exe) <- executable() || {:error, :no_usbport} do
      args = ["open", device] ++ if(i = opts[:interface], do: [to_string(i)], else: [])

      port =
        Port.open({:spawn_executable, exe}, [:binary, :exit_status, {:packet, 4}, args: args])

      receive do
        {^port, {:data, <<"O", bulk_in, bulk_out, int_in, max_packet::16-little>>}} ->
          {:ok,
           %{
             port: port,
             bulk_in: bulk_in,
             bulk_out: bulk_out,
             int_in: int_in,
             max_packet: max_packet
           }}

        {^port, {:data, <<"E", status::32-little-signed>>}} ->
          close_port(port)
          {:error, errno(status)}

        {^port, {:exit_status, code}} ->
          {:error, {:usbport_exited, code}}
      after
        5_000 ->
          close_port(port)
          {:error, :timeout}
      end
    end
  end

  @impl true
  def close(%{port: port}), do: close_port(port)

  @impl true
  def write(s, bin, timeout) do
    case call(s, <<"W", s.bulk_out, timeout::32-little, bin::binary>>, timeout) do
      {:ok, <<"w", n::32-little-signed>>} when n >= 0 -> {:ok, s}
      {:ok, <<"w", n::32-little-signed>>} -> {:error, errno(n), s}
      {:error, reason} -> {:error, reason, s}
    end
  end

  # The kernel copies each transfer through one contiguous buffer; on a Pi, 1 MB of that often
  # isn't there (ENOMEM). 64 KB always is, and a 25 MB RAW is still only a few hundred requests.
  @max_transfer 65_536

  @impl true
  def read(s, max, timeout) do
    max = min(max, @max_transfer)

    case call(s, <<"R", s.bulk_in, timeout::32-little, max::32-little>>, timeout) do
      {:ok, <<"r", n::32-little-signed, data::binary>>} when n >= 0 -> {:ok, data, s}
      {:ok, <<"r", n::32-little-signed, _::binary>>} -> {:error, errno(n), s}
      {:error, reason} -> {:error, reason, s}
    end
  end

  @impl true
  def event(%{int_in: 0} = s, _timeout), do: {:none, s}

  def event(s, timeout) do
    case call(s, <<"I", s.int_in, timeout::32-little, 64::32-little>>, timeout) do
      {:ok, <<"i", n::32-little-signed, data::binary>>} when n > 0 -> {:ok, data, s}
      {:ok, <<"i", _::32-little-signed, _::binary>>} -> {:none, s}
      {:error, :timeout} -> {:none, s}
      {:error, reason} -> {:error, reason, s}
    end
  end

  @doc "Clear a stalled endpoint (after a cancelled transfer)."
  def clear(s, endpoint) do
    case call(s, <<"C", endpoint>>, 2_000) do
      {:ok, <<"c", 0::32>>} -> :ok
      {:ok, <<"c", n::32-little-signed>>} -> {:error, errno(n)}
      error -> error
    end
  end

  # one request, one reply; the helper's own timeout comes first, ours is the backstop
  defp call(%{port: port}, req, timeout) do
    send(port, {self(), {:command, req}})

    receive do
      {^port, {:data, reply}} -> {:ok, reply}
      {^port, {:exit_status, code}} -> {:error, {:usbport_exited, code}}
    after
      timeout + 2_000 -> {:error, :timeout}
    end
  end

  defp close_port(port) do
    try do
      Port.close(port)
    rescue
      _ -> :ok
    end

    :ok
  end

  defp errno(-110), do: :timeout
  defp errno(-60), do: :timeout
  defp errno(-19), do: :no_device
  defp errno(-32), do: :stall
  defp errno(-16), do: :busy
  defp errno(-13), do: :no_access
  defp errno(-38), do: :not_supported_here
  defp errno(-78), do: :not_supported_here
  defp errno(-12), do: :no_kernel_memory
  defp errno(n), do: {:errno, -n}
end
