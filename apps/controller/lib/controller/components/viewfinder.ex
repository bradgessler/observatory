defmodule Controller.Components.Viewfinder do
  @moduledoc """
  What the telescope sees, where you move the telescope: the telescope
  camera's latest picture, small, on a page for driving the mount (the
  keypad), with one line on how fresh it is. Tapping it opens the camera's
  own page. Drawn from a camera status (`Controller.ScopeCamera.find/0`,
  kept fresh by the page's `{:scope_camera, _}` messages), so it shows the
  camera on a box from the Mac too. Nothing at all when there's no camera.

      <.viewfinder cam={@cam} />
  """
  use Phoenix.Component
  use Controller, :verified_routes

  alias Controller.ScopeCamera

  attr :cam, :map, default: nil
  attr :class, :any, default: nil

  def viewfinder(assigns) do
    frame = Enum.find((assigns.cam || %{})[:frames] || [], &(&1[:ok] != false))
    assigns = assign(assigns, frame: frame, line: Controller.CamerasLive.telescope_line(assigns.cam || %{camera: nil}, frame, DateTime.utc_now()))

    ~H"""
    <figure :if={@cam && @cam[:camera]} class={["viewfinder", @class]}>
      <.link navigate={~p"/cameras/telescope"} class="viewfinder-pic" aria-label="What the telescope sees: open the telescope camera">
        <img :if={@frame} src={ScopeCamera.src(@cam, @frame.seq)} alt={"What the telescope sees, frame #{@frame.seq}"} />
        <span :if={!@frame} class="dim">No picture yet: Live View is on the telescope camera's page</span>
      </.link>
      <figcaption class="dim">Telescope camera · {@line}</figcaption>
    </figure>
    """
  end
end
