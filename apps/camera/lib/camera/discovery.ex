defmodule Camera.Discovery do
  @moduledoc """
  Keeps one `Camera.Server` per camera plugged in. Every few seconds it looks
  at the USB bus: on Linux it reads `/sys/bus/usb/devices` itself, on macOS it
  asks `usbport list`. A still-image (PTP) interface is a camera it can drive;
  a Sony that shows up as a disk is one it can't, yet, and it says so:

  > The Sony ILCE-6000 is in USB storage mode: turn it on before plugging the
  > cable in, or set USB Connection to PC Remote.

  A camera whose process keeps failing (5 starts in a minute) is left alone
  with one line saying so, until it's unplugged and plugged back in. With
  `config :camera, simulate: true` (a Mac without a camera, tests) a simulated
  a6000 runs as `"sim-a6000"`.
  """
  use GenServer
  require Logger

  @scan_ms 3_000
  @budget 5
  @window_ms 60_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Cameras running now, with their status."
  def list do
    Registry.select(Camera.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Enum.sort()
    |> Enum.map(&Camera.Server.status/1)
    |> Enum.reject(&is_nil/1)
  end

  @doc """
  Everything the last scan saw: cameras it drives, and cameras it can't
  (`:storage_mode`, `:gave_up`), each with a line for a page.
  """
  def seen, do: GenServer.call(__MODULE__, :seen)

  @doc "Scan now."
  def scan, do: GenServer.call(__MODULE__, :scan)

  @impl true
  def init(opts) do
    send(self(), :scan)

    {:ok,
     %{
       sim: Keyword.get(opts, :simulate, Application.get_env(:camera, :simulate, false)),
       seen: [],
       starts: %{},
       gave_up: MapSet.new()
     }}
  end

  @impl true
  def handle_call(:seen, _from, s), do: {:reply, s.seen, s}

  def handle_call(:scan, _from, s) do
    s = scan(s)
    {:reply, s.seen, s}
  end

  @impl true
  def handle_info(:scan, s) do
    Process.send_after(self(), :scan, @scan_ms)
    {:noreply, scan(s)}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp scan(s) do
    found =
      usb_cameras() ++
        if(s.sim,
          do: [
            %{
              id: "sim-a6000",
              device: nil,
              transport: {Camera.Transport.Sim, []},
              mode: :ptp,
              name: "Simulated ILCE-6000"
            }
          ],
          else: []
        )

    present = MapSet.new(found, & &1.id)

    # unplugged: stop its process, and forget any giving-up (a replug is a fresh start)
    for id <- running(), not MapSet.member?(present, id), do: stop(id)
    gave_up = MapSet.intersection(s.gave_up, present)

    s = Enum.reduce(Enum.filter(found, &(&1.mode == :ptp)), %{s | gave_up: gave_up}, &ensure/2)

    seen =
      Enum.map(found, fn c ->
        cond do
          c.mode == :storage ->
            Map.put(
              c,
              :says,
              "The #{c.name} is in USB storage mode: turn it on before plugging the cable in, or set USB Connection to PC Remote."
            )

          MapSet.member?(s.gave_up, c.id) ->
            Map.merge(c, %{
              mode: :gave_up,
              says:
                "The #{c.name} keeps failing, so it's left alone: unplug it and plug it back in to try again."
            })

          true ->
            c
        end
      end)

    %{s | seen: seen}
  end

  defp ensure(c, s) do
    cond do
      c.id in running() or MapSet.member?(s.gave_up, c.id) ->
        s

      true ->
        now = System.monotonic_time(:millisecond)
        recent = Enum.filter(Map.get(s.starts, c.id, []), &(now - &1 < @window_ms))

        if length(recent) >= @budget do
          Logger.warning(
            "camera #{c.id}: #{@budget} starts in a minute, giving up until it's replugged"
          )

          %{s | gave_up: MapSet.put(s.gave_up, c.id)}
        else
          spec = {Camera.Server, id: c.id, transport: c.transport, device: c.device}

          case DynamicSupervisor.start_child(Camera.Supervisor, spec) do
            {:ok, _} -> :ok
            {:error, {:already_started, _}} -> :ok
            {:error, reason} -> Logger.warning("camera #{c.id}: #{inspect(reason)}")
          end

          %{s | starts: Map.put(s.starts, c.id, [now | recent])}
        end
    end
  end

  defp running, do: Registry.select(Camera.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])

  defp stop(id) do
    case Registry.lookup(Camera.Registry, id) do
      [{pid, _}] -> DynamicSupervisor.terminate_child(Camera.Supervisor, pid)
      [] -> :ok
    end
  end

  # -- the bus -------------------------------------------------------------------------------------

  @sony 0x054C

  defp usb_cameras do
    case :os.type() do
      {:unix, :linux} ->
        linux_cameras(Application.get_env(:camera, :sysfs, "/sys/bus/usb/devices"))

      {:unix, :darwin} ->
        mac_cameras()

      _ ->
        []
    end
  end

  @doc false
  # every USB device with a still-image interface (class 6), and Sony cameras that show up as a disk
  def linux_cameras(sysfs) do
    case File.ls(sysfs) do
      {:ok, names} ->
        names
        |> Enum.reject(&String.contains?(&1, ":"))
        |> Enum.flat_map(fn d ->
          p = Path.join(sysfs, d)
          vendor = hex(read(p, "idVendor"))
          class = hex(read(p <> ":1.0", "bInterfaceClass"))
          name = String.trim("#{read(p, "manufacturer")} #{read(p, "product")}")

          cond do
            class == 6 ->
              dev =
                :io_lib.format("/dev/bus/usb/~3..0B/~3..0B", [
                  int(read(p, "busnum")),
                  int(read(p, "devnum"))
                ])
                |> to_string()

              [
                %{
                  id: id_for(name, read(p, "serial")),
                  device: dev,
                  transport: {Camera.Transport.Usb, device: dev},
                  mode: :ptp,
                  name: name
                }
              ]

            vendor == @sony and class == 8 ->
              [
                %{
                  id: id_for(name, read(p, "serial")),
                  device: nil,
                  transport: nil,
                  mode: :storage,
                  name: name
                }
              ]

            true ->
              []
          end
        end)

      _ ->
        []
    end
  end

  defp mac_cameras do
    case Camera.Transport.Usb.executable() do
      nil ->
        []

      exe ->
        case System.cmd(exe, ["list"], stderr_to_stdout: true) do
          {out, 0} ->
            for "D " <> rest <- String.split(out, "\n", trim: true),
                [head, man, prod] <- [String.split(rest, "\t")],
                [spec, _vid, _pid, iface] <- [String.split(head, " ")] do
              name = String.trim("#{man} #{prod}")

              %{
                id: id_for(name, spec),
                device: spec,
                transport:
                  {Camera.Transport.Usb, device: spec, interface: String.to_integer(iface)},
                mode: :ptp,
                name: name
              }
            end

          _ ->
            []
        end
    end
  end

  # a name a person recognises, the same every time the camera is plugged in: "sony-ilce-6000"
  defp id_for(name, _serial) do
    name
    |> String.downcase()
    |> String.replace(~r/corporation|inc\.?|co\.,? ltd\.?/, "")
    |> String.replace(~r/[^a-z0-9]+/, "-")
    |> String.trim("-")
  end

  defp read(dir, file) do
    case File.read(Path.join(dir, file)) do
      {:ok, v} -> String.trim(v)
      _ -> ""
    end
  end

  defp hex(v) do
    case Integer.parse(v, 16) do
      {n, _} -> n
      :error -> nil
    end
  end

  defp int(v) do
    case Integer.parse(v) do
      {n, _} -> n
      :error -> 0
    end
  end
end
