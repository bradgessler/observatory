defmodule Input do
  @moduledoc """
  Hardware inputs (game controllers and other HID devices) read by the server.

  The machine the device is plugged into runs `Input.Discovery`, which opens a
  `Input.Device` per gamepad; every state change is broadcast on `"input"` as
  `{:input, id, info}`. `Input.Mapper` turns that into mount motion. Any page
  on any node can `subscribe/0` and show what's happening.

      iex> Input.devices()
      [%{id: "045e:0028@…", parser: "SideWinder Dual Strike", state: %{axes: [...], buttons: [...]}, ...}]
      iex> Input.arm(true)
  """

  def subscribe, do: Telescope.subscribe("input")

  @doc "Open devices with their latest state."
  def devices do
    Registry.select(Input.Registry, [{{:"$1", :_, :_}, [], [:"$1"]}])
    |> Enum.map(fn id ->
      try do
        Input.Device.state(id)
      catch
        _, _ -> nil
      end
    end)
    |> Enum.reject(&is_nil/1)
  end

  @doc "Every HID device the OS lists, reading or not."
  def seen, do: Input.Discovery.seen()

  defdelegate scan, to: Input.Discovery
  defdelegate status, to: Input.Mapper
  defdelegate arm(on?), to: Input.Mapper
  defdelegate target(mount_id), to: Input.Mapper
  defdelegate configure(map), to: Input.Mapper
end
