defmodule Firmware.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = target_children()
    Supervisor.start_link(children, strategy: :one_for_one, name: Firmware.Supervisor)
  end

  if Mix.target() == :host do
    defp target_children, do: []
  else
    defp target_children do
      [
        # the flight recorder: on the SD card, so a reset leaves a record
        Firmware.Blackbox,
        Firmware.Distribution,
        Firmware.Wireless,
        # phones that have been through the captive page, this boot
        Firmware.Web.Captive,
        # keeps a new image only once its page and network are up
        Firmware.Health
      ]
    end
  end
end
