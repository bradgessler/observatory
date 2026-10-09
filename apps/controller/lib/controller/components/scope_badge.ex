defmodule Controller.Components.ScopeBadge do
  @moduledoc """
  One telescope, small: a drawing of how it is standing, its name, one state
  word and the two axis angles. The status strip's picture-first sibling.

  The numbers are where the two axes stand, in degrees from where they were
  zeroed, and are labelled as that: "RA axis", "Dec axis". They were once
  labelled "RA" and "Dec", which on an aligned mount reads as a place on the
  sky, and they are not one.

  The drawing gets a rim in the text ink (`Scope.scope`'s `outline`): its
  faces alone are too close to the card's ground to see, most of all in night
  mode.

  Several of these sit in a row, because several telescopes is where this is
  going: an alt-az beside the equatorial, a friend's mount at a star party.
  A tap goes to that mount's Setup.
  """
  use Phoenix.Component
  use Controller, :verified_routes

  alias Controller.Components.Scope

  attr :id, :string, required: true
  attr :snap, :map, default: nil
  attr :pose, :map, default: nil
  attr :holding, :string, default: nil
  attr :navigate, :string, default: nil
  attr :where, :string, default: nil, doc: "the box it is on, when that is not this machine"
  attr :class, :string, default: nil

  def badge(assigns) do
    assigns =
      assign(assigns,
        state: state_words(assigns.snap, assigns.holding),
        tone: tone(assigns.snap, assigns.holding),
        name: short(assigns.id)
      )

    ~H"""
    <.link
      :if={@navigate}
      navigate={@navigate}
      class={["scope-badge", @class]}
      aria-label={"#{@name}: #{@state}#{numbers_words(@snap)}"}
    >
      <.inside {assigns} />
    </.link>
    <div :if={!@navigate} class={["scope-badge", @class]} aria-label={"#{@name}: #{@state}"}>
      <.inside {assigns} />
    </div>
    """
  end

  defp inside(assigns) do
    ~H"""
    <span class="sb-pic">
      <Scope.scope :if={@pose} pose={@pose} size={104} detail={false} outline label={@name} />
      <span :if={!@pose} class="sb-blank" aria-hidden="true"></span>
    </span>
    <span class="sb-text">
      <strong>{@name}</strong>
      <span class={["sb-state", @tone]}>{@state}</span>
      <%!-- each number beside what it is; a pair stays whole when the two don't fit on one line --%>
      <span :if={@snap && @snap[:axes][:ra]} class="sb-nums">
        <span class="sb-num">RA axis {deg(@snap.axes.ra.degrees)}</span>
        <span class="sb-num">Dec axis {deg(@snap.axes.dec.degrees)}</span>
      </span>
      <span :if={@snap && @snap[:id] && Mount.simulated?(@id)} class="sb-sim">Simulator</span>
      <span :if={@where} class="sb-where">on {@where}</span>
    </span>
    """
  end

  @doc "A serial port's name is mostly noise; keep the tail that tells cables apart."
  def short("cu.usbserial-" <> tail), do: tail
  def short("tty.usbserial-" <> tail), do: tail
  def short(id), do: id

  defdelegate sim?(id), to: Mount, as: :simulated?

  defp state_words(nil, _), do: "Not connected"
  defp state_words(%{connected: false}, _), do: "Not answering (switched off?)"

  defp state_words(snap, holding) do
    cond do
      holding != nil -> "Tracking #{holding}"
      Enum.any?(snap.axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end) -> "Slewing"
      snap.tracking != :off -> "Tracking"
      Enum.any?(snap.axes, fn {_, ax} -> ax.running end) -> "Moving"
      snap.homed -> "Home set, still"
      true -> "Home not set"
    end
  end

  defp tone(nil, _), do: "warn"
  # switched off is not an emergency: red is for STOP and real warnings
  defp tone(%{connected: false}, _), do: "dim"
  defp tone(snap, holding) do
    cond do
      # holding is a name or nil, never a boolean
      holding != nil -> "on"
      snap.tracking != :off -> "on"
      snap.homed -> "on"
      true -> "dim"
    end
  end

  defp numbers_words(%{axes: %{ra: ra, dec: dec}}), do: ", RA axis #{deg(ra.degrees)}, Dec axis #{deg(dec.degrees)}"
  defp numbers_words(_), do: ""

  defp deg(d) when is_number(d) do
    sign = if d < 0, do: "−", else: "+"
    a = abs(d)
    "#{sign}#{trunc(a)}°#{:erlang.float_to_binary((a - trunc(a)) * 60, decimals: 0) |> String.pad_leading(2, "0")}′"
  end

  defp deg(_), do: Controller.Words.none()
end
