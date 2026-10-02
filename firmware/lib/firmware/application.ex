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
        # what the radio hears, kept apart from the stack so it outlives a restart
        Firmware.Bluetooth.Nearby,
        # BlueZ behind a circuit breaker: its failures stop at Bluetooth
        {Firmware.Bluetooth, Application.get_env(:firmware, :bluetooth, [])},
        # The batteries, fenced off: a session per Anker SOLIX battery heard
        # (each temporary) and the process that numbers them. Their own
        # supervisor, itself temporary: if it runs out of restarts the box
        # goes without battery readings, and the Wi-Fi, the mount and the
        # page never notice.
        %{
          id: Firmware.Batteries.Supervisor,
          type: :supervisor,
          restart: :temporary,
          start:
            {Supervisor, :start_link,
             [
               [
                 {DynamicSupervisor, name: Firmware.Batteries.sessions(), strategy: :one_for_one},
                 Firmware.Batteries
               ],
               [strategy: :one_for_all, max_restarts: 5, max_seconds: 60, name: Firmware.Batteries.Supervisor]
             ]}
        },
        # keeps a new image only once its page and network are up
        Firmware.Health
      ]
    end
  end
end
