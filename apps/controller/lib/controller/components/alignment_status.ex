defmodule Controller.Components.AlignmentStatus do
  @moduledoc """
  How well a telescope is aligned, drawn the same way everywhere
  (`Controller.Alignment.summary/1`): a bullseye and a line of words.

  The bullseye's three rings are the three goals, loosest outside: the
  outer ring lights when the margin is good enough to just look (30′), the
  middle for the Moon and planets (10′), the centre for deep sky (2′). With
  one or two points the rings are dashed (they fit exactly, so there's no
  margin yet); with home set and no points, only the centre dot shows. The
  words always say it too ("±3′ · 4 points"), so it never rests on the
  picture alone.

    * `glyph/1`: the bullseye alone;
    * `chip/1`: the sidebar's line under the telescope switcher, a link to
      the Alignment page;
    * `bar/1`: the toolbar status on the Alignment pages, with what it's good for.
  """
  use Phoenix.Component

  attr :summary, :map, required: true
  attr :size, :integer, default: 24
  attr :class, :any, default: nil

  def glyph(assigns) do
    ~H"""
    <svg class={["al-glyph", "al-#{@summary.state}", @class]} viewBox="0 0 24 24" width={@size} height={@size} aria-hidden="true">
      <circle cx="12" cy="12" r="10.5" class={["al-ring", @summary.rings >= 1 && "lit"]} />
      <circle cx="12" cy="12" r="6.8" class={["al-ring", @summary.rings >= 2 && "lit"]} />
      <circle cx="12" cy="12" r="3.2" class={["al-ring", "al-core", @summary.rings >= 3 && "lit"]} />
      <circle :if={@summary.homed or @summary.n > 0} cx="12" cy="12" r="1.2" class="al-dot" />
    </svg>
    """
  end

  @doc "The sidebar's line: the bullseye, Alignment over the words; a link to the Alignment page."
  attr :summary, :map, default: nil
  attr :href, :string, required: true

  def chip(assigns) do
    ~H"""
    <.link :if={@summary} navigate={@href} class={["al-chip", "al-#{@summary.state}"]} aria-label={"Alignment: #{@summary.words}. #{@summary.detail}"}>
      <.glyph summary={@summary} size={22} />
      <span class="al-chip-text"><strong>Alignment</strong><span>{@summary.words}</span></span>
    </.link>
    """
  end

  @doc "The Alignment pages' toolbar status: the bullseye, the words, and what it's good for."
  attr :summary, :map, default: nil

  def bar(assigns) do
    ~H"""
    <div :if={@summary} class={["al-bar", "al-#{@summary.state}"]} role="status" aria-live="polite">
      <.glyph summary={@summary} size={32} />
      <span class="al-bar-text"><strong>{@summary.words}</strong><span>{@summary.detail}</span></span>
    </div>
    """
  end
end
