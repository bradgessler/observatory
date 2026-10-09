defmodule Telescope.Boxes do
  @moduledoc """
  Observatory boxes on this network, found and connected.

  A box advertises its Erlang node over mDNS (`_epmd._tcp.local`, with its node
  name in the record's text, `node=telescope@observatory.local`). This asks
  every 10 s, in plain Elixir (a multicast query and `:inet_dns`), and lists
  what answered. `connect/1` joins a box's node: its mounts then appear in
  `Mount.list/0` and every page can drive them, its snapshots arriving through
  the cluster's PubSub. A connected box is remembered (`:boxes_file`) and
  reconnected whenever it drops, every 5 s: a box that reboots comes back.

  A box whose record has no node name (an older image) can still be connected
  by typing its node name; its address shows here either way.

      Telescope.Boxes.list()
      Telescope.Boxes.connect(:"telescope@observatory.local")
  """
  use GenServer

  @topic "boxes"
  @browse_ms 10_000
  @reconnect_ms 5_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Boxes seen or remembered: `%{name, node, ip, connected, remembered}`, by name."
  def list do
    GenServer.call(__MODULE__, :list)
  catch
    :exit, _ -> []
  end

  @doc "Join a box's node, and keep it joined."
  def connect(node) when is_atom(node), do: GenServer.call(__MODULE__, {:connect, node}, 10_000)
  def connect(node) when is_binary(node), do: connect(String.to_atom(String.trim(node)))

  @doc "Leave a box's node and stop reconnecting to it."
  def forget(node) when is_atom(node), do: GenServer.call(__MODULE__, {:forget, node})
  def forget(node) when is_binary(node), do: forget(String.to_atom(node))

  def subscribe, do: Telescope.subscribe(@topic)

  # -- the process ------------------------------------------------------------------------

  @impl true
  def init(opts) do
    :net_kernel.monitor_nodes(true)
    send(self(), :browse)
    send(self(), :reconnect)
    {:ok, %{seen: %{}, remembered: load(opts[:file]), file: opts[:file]}}
  end

  @impl true
  def handle_call(:list, _from, state), do: {:reply, boxes(state), state}

  def handle_call({:connect, node}, _from, state) do
    result = Node.alive?() and Node.connect(node) == true
    state = if result, do: remember(state, node), else: state
    changed(state)
    {:reply, if(result, do: :ok, else: {:error, :no_answer}), state}
  end

  def handle_call({:forget, node}, _from, state) do
    Node.disconnect(node)
    state = %{state | remembered: MapSet.delete(state.remembered, node)}
    save(state)
    changed(state)
    {:reply, :ok, state}
  end

  @impl true
  def handle_info(:browse, state) do
    Process.send_after(self(), :browse, @browse_ms)
    seen = browse() |> Map.new(&{&1.name, &1})
    if seen != state.seen, do: changed(%{state | seen: seen})
    {:noreply, %{state | seen: seen}}
  end

  def handle_info(:reconnect, state) do
    Process.send_after(self(), :reconnect, @reconnect_ms)

    if Node.alive?() do
      for node <- state.remembered, node not in Node.list(), do: Node.connect(node)
    end

    {:noreply, state}
  end

  def handle_info({event, _node}, state) when event in [:nodeup, :nodedown] do
    changed(state)
    {:noreply, state}
  end

  def handle_info(_, state), do: {:noreply, state}

  # -- the list ---------------------------------------------------------------------------

  defp boxes(state) do
    # a remembered node, and the address its host name resolves to: a box
    # that does not say its node name is the same box when the addresses match
    remembered = for node <- state.remembered, do: {node, address(node)}

    seen =
      for {_, b} <- state.seen do
        node = b.node || Enum.find_value(remembered, fn {n, ip} -> if ip == b.ip, do: n end)
        Map.merge(b, %{node: node, connected: node in Node.list(), remembered: node in state.remembered})
      end

    seen_nodes = MapSet.new(seen, & &1.node)

    unseen =
      for {node, ip} <- remembered, node not in seen_nodes do
        %{name: host(node), node: node, ip: ip, connected: node in Node.list(), remembered: true}
      end

    Enum.sort_by(seen ++ unseen, & &1.name)
  end

  defp host(node), do: node |> to_string() |> String.split("@") |> List.last()

  defp address(node) do
    case :inet.getaddr(String.to_charlist(host(node)), :inet) do
      {:ok, ip} -> ip |> :inet.ntoa() |> to_string()
      _ -> nil
    end
  end

  defp changed(state), do: Telescope.broadcast(@topic, {:boxes, boxes(state)})

  defp remember(state, node) do
    state = %{state | remembered: MapSet.put(state.remembered, node)}
    save(state)
    state
  end

  # -- mDNS -------------------------------------------------------------------------------

  @doc false
  def browse(timeout \\ 1_500) do
    query =
      :inet_dns.make_msg(
        header: :inet_dns.make_header(id: 0, opcode: :query, rd: false),
        qdlist: [:inet_dns.make_dns_query(domain: ~c"_epmd._tcp.local", type: :ptr, class: :in)]
      )

    case :gen_udp.open(0, [:binary, active: false, multicast_ttl: 255, multicast_loop: false]) do
      {:ok, socket} ->
        try do
          :ok = :gen_udp.send(socket, {224, 0, 0, 251}, 5353, :inet_dns.encode(query))
          socket |> answers(timeout, []) |> Enum.flat_map(&box/1) |> Enum.uniq_by(& &1.name)
        after
          :gen_udp.close(socket)
        end

      _ ->
        []
    end
  end

  defp answers(socket, timeout, acc) do
    case :gen_udp.recv(socket, 0, timeout) do
      {:ok, {ip, _port, data}} -> answers(socket, timeout, [{ip, data} | acc])
      _ -> acc
    end
  end

  defp box({ip, data}) do
    with {:ok, msg} <- :inet_dns.decode(data) do
      records = for rr <- :inet_dns.msg(msg, :anlist) ++ :inet_dns.msg(msg, :arlist), do: {:inet_dns.rr(rr, :type), :inet_dns.rr(rr, :data)}

      instance =
        Enum.find_value(records, fn
          {:ptr, name} -> name |> to_string() |> String.replace_suffix("._epmd._tcp.local", "")
          _ -> nil
        end)

      node =
        Enum.find_value(records, fn
          {:txt, strings} -> Enum.find_value(strings, &(to_string(&1) |> String.replace_prefix("node=", "") |> then(fn s -> if s != to_string(&1), do: String.to_atom(s) end)))
          _ -> nil
        end)

      if instance, do: [%{name: instance, node: node, ip: ip |> :inet.ntoa() |> to_string()}], else: []
    else
      _ -> []
    end
  end

  # -- remembered boxes -------------------------------------------------------------------

  defp load(nil), do: MapSet.new()

  # one node per line
  defp load(path) do
    case File.read(path) do
      {:ok, text} -> text |> String.split("\n", trim: true) |> MapSet.new(&String.to_atom/1)
      _ -> MapSet.new()
    end
  end

  defp save(%{file: nil}), do: :ok

  defp save(%{file: path, remembered: nodes}) do
    File.mkdir_p(Path.dirname(path))
    File.write(path, Enum.map_join(nodes, "", &"#{&1}\n"))
  end
end
