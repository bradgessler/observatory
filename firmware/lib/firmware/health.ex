defmodule Firmware.Health do
  @moduledoc """
  A new image is kept only once it can actually be used.

  After an update over the network the box runs the new image on trial, and
  Nerves' own guard (`startup_guard_enabled: true`) keeps it as soon as every
  app has started. That misses the failure that matters most in a field: an
  image that starts fine but has broken the network, so nobody can reach the
  box to fix it. This adds the check that counts: the page answers on port 80
  and an interface has an address (wlan0 as client or access point, or a
  cable). Not both within five minutes of the first boot of an image, and the
  box reverts to the image it had before, and reboots into it.

  The stock guard stays on, because it also does the heart handshake that
  catches an image hanging before this ever runs. Each image is checked once:
  its UUID is recorded when it passes, so later boots of a good image cost
  nothing, and the image reverted to (older, without this module) cannot loop.
  """
  use GenServer
  require Logger

  @compile {:no_warn_undefined, [Nerves.Runtime, Nerves.Runtime.KV, VintageNet]}

  @key "obs_healthy_uuid"
  @check_every 5_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Whether this image has passed (it has, on any boot after its first)."
  def passed?, do: GenServer.call(__MODULE__, :passed?)

  @impl true
  def init(_) do
    uuid = Nerves.Runtime.KV.get_active("nerves_fw_uuid")

    # Nothing to go back to on a freshly stamped card (the other slot is empty),
    # so only an image that replaced another one is put on trial.
    if uuid in [nil, ""] or Nerves.Runtime.KV.get(@key) == uuid or not previous_image?() do
      {:ok, %{uuid: uuid, passed: true}}
    else
      Logger.info("image #{uuid} on trial: waiting for the page and the network")
      Process.send_after(self(), :give_up, Application.get_env(:firmware, :health_within_ms, 300_000))
      send(self(), :check)
      {:ok, %{uuid: uuid, passed: false}}
    end
  end

  @impl true
  def handle_call(:passed?, _from, state), do: {:reply, state.passed, state}

  @impl true
  def handle_info(:check, %{passed: false} = state) do
    if page_answers?() and addressed?() do
      Logger.info("image #{state.uuid} is healthy: page up, network up; keeping it")
      Nerves.Runtime.KV.put(@key, state.uuid)
      {:noreply, %{state | passed: true}}
    else
      Process.send_after(self(), :check, @check_every)
      {:noreply, state}
    end
  end

  def handle_info(:give_up, %{passed: false} = state) do
    Logger.error("image #{state.uuid}: page or network not up in time; reverting to the previous image")
    # reboots on success; on a card that has no previous image there is nothing
    # to go back to, and the box stays as it is
    Nerves.Runtime.revert()
    {:noreply, state}
  end

  def handle_info(_, state), do: {:noreply, state}

  defp previous_image? do
    other = if Nerves.Runtime.KV.get("nerves_fw_active") == "b", do: "a", else: "b"
    Nerves.Runtime.KV.get(other <> ".nerves_fw_uuid") not in [nil, ""]
  end

  # A real request, so a page that is listening but broken does not pass.
  defp page_answers? do
    with {:ok, socket} <- :gen_tcp.connect({127, 0, 0, 1}, 80, [:binary, active: false], 2_000),
         :ok <- :gen_tcp.send(socket, "GET / HTTP/1.0\r\nHost: localhost\r\n\r\n"),
         {:ok, reply} <- :gen_tcp.recv(socket, 0, 5_000) do
      :gen_tcp.close(socket)
      String.starts_with?(reply, "HTTP/1.1 200") or String.starts_with?(reply, "HTTP/1.0 200")
    else
      _ -> false
    end
  end

  defp addressed? do
    Enum.any?(["wlan0", "eth0", "usb0"], fn ifname ->
      Enum.any?(VintageNet.get(["interface", ifname, "addresses"]) || [], &match?(%{address: {_, _, _, _}}, &1))
    end)
  end
end
