defmodule Firmware.Distribution do
  @moduledoc """
  Starts Erlang distribution as `telescope@telescope.local` once the box has an
  address, so a laptop on the same network (Wi-Fi, ethernet, or the USB cable)
  can `Node.connect(:"telescope@telescope.local")` and call `Mount` directly.
  Retries quietly until networking is up.
  """
  use GenServer
  require Logger

  @retry_ms 2_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(_) do
    send(self(), :try)
    {:ok, %{}}
  end

  @impl true
  def handle_info(:try, state) do
    if Node.alive?() do
      {:noreply, state}
    else
      name = Application.get_env(:firmware, :node_name, "telescope")
      node = :"#{name}@#{name}.local"

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
