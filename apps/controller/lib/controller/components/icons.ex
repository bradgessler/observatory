defmodule Controller.Components.Icons do
  @moduledoc """
  The few icons the navigation uses, drawn here (which page gets which is
  `Controller.Nav`'s, beside the page's name): 24-unit grid, 1.75 stroke,
  round ends, `currentColor`, so they take the ink of whatever holds them
  (dim in a row, bright on the current page, red at night). Decorative: the
  label beside each one says what it is, so they are hidden from screen
  readers.

      <.icon name="wifi" />
  """
  use Phoenix.Component

  attr :name, :string, required: true
  attr :class, :string, default: "icon"

  def icon(assigns) do
    ~H"""
    <svg class={@class} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
      {Phoenix.HTML.raw(path(@name))}
    </svg>
    """
  end

  defp path("play"), do: ~S|<path d="M8 5.5v13l10.5-6.5z"/>|
  defp path("star"), do: ~S|<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>|
  defp path("snap"), do: ~S|<path d="M4 8h3l1.8-2.5h6.4L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><path d="M12 10.5v5M9.5 13h5"/>|
  defp path("moon"), do: ~S|<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>|
  defp path("globe"), do: ~S|<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><ellipse cx="12" cy="12" rx="3.6" ry="8.5"/>|
  defp path("aperture"), do: ~S|<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.5"/>|
  defp path("telescope"), do: ~S|<path d="M3.5 13.5l12.5-6 1.8 3.7-12.5 6z"/><path d="M17.9 7.6l2.3-1.1 1.4 2.9-2.3 1.1"/><path d="M10.5 15.6L8 21"/><path d="M12 15l3 6"/>|
  defp path("orbit"), do: ~S|<circle cx="12" cy="12" r="5"/><ellipse cx="12" cy="12" rx="10" ry="3.8" transform="rotate(-20 12 12)"/>|
  defp path("crosshair"), do: ~S|<circle cx="12" cy="12" r="7"/><path d="M12 2.5v5M12 16.5v5M2.5 12h5M16.5 12h5"/>|
  defp path("sliders"), do: ~S|<path d="M4 8h16M4 16h16"/><rect x="7" y="6" width="4" height="4" rx="1"/><rect x="13" y="14" width="4" height="4" rx="1"/>|
  defp path("dpad"), do: ~S|<path d="M9 3.5h6v5.5h5.5v6H15v5.5H9V15H3.5V9H9z"/>|
  defp path("nudge"), do: ~S|<path d="M12 4v4M12 16v4M4 12h4M16 12h4"/><path d="M10.5 5.5L12 4l1.5 1.5M10.5 18.5L12 20l1.5-1.5M5.5 10.5L4 12l1.5 1.5M18.5 10.5L20 12l-1.5 1.5"/><circle cx="12" cy="12" r="1"/>|
  defp path("center"), do: ~S|<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 3.5v4M12 16.5v4M3.5 12h4M16.5 12h4"/>|
  defp path("pin"), do: ~S|<path d="M12 21s-6.5-5.6-6.5-10.5a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z"/><circle cx="12" cy="10.5" r="2.2"/>|
  defp path("gamepad"), do: ~S|<path d="M7 8h10a4 4 0 0 1 3.9 3.1l.9 4.4a2.4 2.4 0 0 1-4.2 2L16 16H8l-1.6 1.5a2.4 2.4 0 0 1-4.2-2l.9-4.4A4 4 0 0 1 7 8z"/><path d="M8 10.5v3M6.5 12h3"/><path d="M15.5 11.5h.01M17.5 13h.01"/>|
  defp path("video"), do: ~S|<rect x="3" y="6" width="12.5" height="12" rx="2"/><path d="M15.5 10.5L21 7.5v9l-5.5-3z"/>|
  defp path("frames"), do: ~S|<rect x="3" y="4.5" width="14" height="11" rx="2"/><path d="M7 19.5h11a2.5 2.5 0 0 0 2.5-2.5V8.5"/><path d="M3.5 13l3.5-3 3 2.5 2.5-2 4 3.5"/>|
  defp path("camera"), do: ~S|<path d="M4 8h3l1.8-2.5h6.4L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>|
  defp path("sdcard"), do: ~S|<path d="M9 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7z"/><path d="M10 7v2.5M13 7v2.5M16 7v2.5"/>|
  defp path("bluetooth"), do: ~S|<path d="M7 7l10 10-5 5V2l5 5L7 17"/>|
  defp path("wifi"), do: ~S|<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 13 0"/><path d="M8.8 16a4.8 4.8 0 0 1 6.4 0"/><path d="M12 19.5h.01"/>|
  defp path("box"), do: ~S|<rect x="3.5" y="6.5" width="17" height="11" rx="1.5"/><path d="M7 10.5h4v3H7zM14 10.5h3M14 13.5h3"/>|
  defp path("plug"), do: ~S|<path d="M9 3v4.5M15 3v4.5"/><path d="M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5V21"/>|
  defp path("activity"), do: ~S|<path d="M3 12h4l3-7.5 4 15 3-7.5h4"/>|
  defp path("grid"), do: ~S|<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>|
  defp path("compass"), do: ~S|<circle cx="12" cy="12" r="8.5"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>|
  defp path("house"), do: ~S|<path d="M4 10.5L12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z"/>|
  defp path("chevrons"), do: ~S|<path d="M8 9.5l4-4 4 4M8 14.5l4 4 4-4"/>|
  defp path("check"), do: ~S|<path d="M5 12.5l4.5 4.5L19 7.5"/>|
  defp path("sim"), do: ~S|<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 12h6M12 9v6"/>|
  defp path("cameras"), do: ~S|<rect x="2.5" y="5" width="8.5" height="6.5" rx="1.5"/><rect x="13" y="5" width="8.5" height="6.5" rx="1.5"/><rect x="2.5" y="13.5" width="8.5" height="6.5" rx="1.5"/><rect x="13" y="13.5" width="8.5" height="6.5" rx="1.5"/><circle cx="6.75" cy="8.25" r="1.2"/><circle cx="17.25" cy="8.25" r="1.2"/>|
  defp path("focus"), do: ~S|<path d="M4 8.5V5.5A1.5 1.5 0 0 1 5.5 4h3M15.5 4h3A1.5 1.5 0 0 1 20 5.5v3M20 15.5v3a1.5 1.5 0 0 1-1.5 1.5h-3M8.5 20h-3A1.5 1.5 0 0 1 4 18.5v-3"/><circle cx="12" cy="12" r="3"/>|
  defp path("gear"), do: ~S|<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>|
  defp path("queue"), do: ~S|<rect x="3.5" y="4" width="17" height="4" rx="1.5"/><rect x="3.5" y="10" width="17" height="4" rx="1.5"/><path d="M3.5 18h10"/>|
  defp path("layers"), do: ~S|<path d="M12 3.5l9 4.5-9 4.5-9-4.5z"/><path d="M3 12l9 4.5 9-4.5"/><path d="M3 16l9 4.5 9-4.5"/>|
  defp path("back"), do: ~S|<path d="M14.5 5.5L8 12l6.5 6.5"/>|
  defp path("search"), do: ~S|<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/>|
  defp path("close"), do: ~S|<path d="M6 6l12 12M18 6L6 18"/>|
  defp path("help"), do: ~S|<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.7"/><path d="M12 17h.01"/>|
  defp path(_), do: ~S|<circle cx="12" cy="12" r="2.5"/>|
end
