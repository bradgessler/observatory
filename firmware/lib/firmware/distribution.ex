defmodule Firmware.Distribution do
  @moduledoc """
  Starts Erlang distribution as `telescope@<hostname>.local` once the box has
  an address, so a computer on the same network (Wi-Fi, ethernet, or the USB
  cable) can `Node.connect(:"telescope@observatory.local")` and call `Mount`
  directly. Retries quietly until networking is up.

  Distribution registers with `epmd`, which nothing on a Nerves box starts by
  itself; without it every attempt logs `register/listen error: econnrefused`
  (every 2 s, all night, onto the SD card). So it is started first.
  """
  use GenServer
  require Logger

  @retry_ms 2_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_) do
    _ = System.cmd("epmd", ["-daemon"], stderr_to_stdout: true)
    send(self(), :try)
    {:ok, %{}}
  end

  @impl true
  def handle_info(:try, state) do
    if Node.alive?() do
      {:noreply, state}
    else
      name = Application.get_env(:firmware, :node_name, "telescope")
      host = Application.get_env(:firmware, :name, name)
      node = :"#{name}@#{host}.local"

      case :net_kernel.start([node, :longnames]) do
        {:ok, _} ->
          Logger.info("distribution up as #{node}")

        {:error, reason} ->
          Logger.debug("distribution not yet: #{inspect(reason)}")
          Process.send_after(self(), :try, @retry_ms)
      end

      {:noreply, state}
    end
  end
end
