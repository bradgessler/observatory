defmodule Controller.Components.Modes do
  @moduledoc "The amber 'this mode is on' strip shown on every page while any mode is active."
  use Phoenix.Component
  use Controller, :verified_routes

  attr :modes, :list, required: true
  attr :id, :string, default: nil

  def modes(assigns) do
    ~H"""
    <.link :if={@modes != []} navigate={if @id, do: ~p"/setup/#{@id}", else: ~p"/devices"} class="modes">
      <span :for={{label, detail} <- @modes} class="mode-badge"><strong>{label}</strong> {detail}</span>
      <span class="mode-more">setup ›</span>
    </.link>
    """
  end
end
