defmodule Telescope.Distribution do
  @moduledoc """
  Makes this machine a node of the observatory cluster, so it can reach the
  mounts on other machines (a box on the network) and they can be driven from
  its pages.

  Off unless configured (`config :telescope, distribution: [name: "observatory",
  cookie: :observatory]`); a box starts its own (Firmware.Distribution). The
  node is `name@<hostname>.local`, long names, with the shared cookie.
  Distribution registers with `epmd`, which is started first if it is not
  running. Retries every 2 s until the network lets it.

  The cookie is the only thing between the network and a shell on every node:
  fine on a home network you run, not on one you do not.
  """
  use GenServer
  require Logger

  @retry_ms 2_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @impl true
  def init(opts) do
    send(self(), :try)
    {:ok, Map.new(opts)}
  end

  @impl true
  def handle_info(:try, state) do
    cookie = Map.get(state, :cookie, :observatory)

    if Node.alive?() do
      Node.set_cookie(cookie)
      {:noreply, state}
    else
      _ = epmd()
      {:ok, host} = :inet.gethostname()
      node = :"#{Map.get(state, :name, "observatory")}@#{host}.local"

      case :net_kernel.start([node, :longnames]) do
        {:ok, _} ->
          Node.set_cookie(cookie)
          Logger.info("in the cluster as #{node}")

        {:error, reason} ->
          Logger.debug("cluster not yet: #{inspect(reason)}")
          Process.send_after(self(), :try, @retry_ms)
      end

      {:noreply, state}
    end
  end

  defp epmd do
    case System.find_executable("epmd") || Path.wildcard(Path.join(:code.root_dir(), "erts-*/bin/epmd")) |> List.first() do
      nil -> :no_epmd
      exe -> System.cmd(exe, ["-daemon"], stderr_to_stdout: true)
    end
  end
end
