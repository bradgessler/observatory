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
        Firmware.Distribution,
        Firmware.WifiFallback
      ]
    end
  end
end
