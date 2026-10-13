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
  picture alone. While a mount with no home picks its side of the pier on a
  guess, the words say that as well ("Counterweight side guessed").

    * `glyph/1`: the bullseye alone;
    * `chip/1`: the sidebar's line under the telescope switcher, a link to
      the Alignment page;
    * `bar/1`: the toolbar status on the Alignment pages, with what it's good for;
    * `set_aside/1`: the alignment a reset replaced, with the key that brings
      it back, on every page that can reset one. `restore/1` is that key's
      `"restore_alignment"` event, for the page.
  """
  use Phoenix.Component

  alias Controller.Sky.Lineup

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
      <%!-- a margin says how close Go To lands, not which side of the pier it picks: say when that is a guess --%>
      <span class="al-chip-text"><strong>Alignment</strong><span>{@summary.words}</span><span :if={@summary[:counterweight] == :guessed} class="tone-caution">Counterweight side guessed</span></span>
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

  @doc """
  The alignment a reset replaced, and the key that brings it back: nothing is
  thrown away by clearing, forgetting a point or aligning again
  (`Controller.Sky.Lineup.restore/2`). Draws nothing when none can be brought
  back. `was` is `Controller.Sky.Lineup.restorable/1`.
  """
  attr :was, :map, default: nil
  attr :now, :any, default: nil, doc: "the page's clock, a DateTime; the time now when not given"

  def set_aside(assigns) do
    assigns = assign(assigns, now: assigns.now || DateTime.utc_now())

    ~H"""
    <div :if={@was} class="setting" id="alignment-set-aside">
      <div class="setting-text">
        <strong>Alignment set aside {ago(@was.set_aside_at, @now)}</strong>
        <span>{set_aside_words(@was)}</span>
      </div>
      <span class="setting-action">
        <Controller.Components.UI.btn phx-click="restore_alignment">Restore</Controller.Components.UI.btn>
      </span>
    </div>
    """
  end

  @doc ~S("4 points agree to 0.4′. A new alignment replaced it.")
  def set_aside_words(was) do
    why = if is_binary(was.why), do: " " <> Controller.Components.UI.sentence(was.why) <> ".", else: ""
    points_words(was.n, was.rms_arcmin) <> "." <> why
  end

  @doc "A tap on Restore, for the page's event: brings the alignment back and says what happened in one line."
  def restore(nil), do: "No mount"

  def restore(id) do
    case Lineup.restore(id) do
      {:ok, st} -> "Alignment restored: " <> points_words(st.n, st.rms_arcmin)
      {:error, :stale} -> "That alignment no longer holds: the mount was switched off and on, or home was set again"
      {:error, :another_night} -> "That alignment is from another night"
      {:error, :nothing} -> "No alignment set aside"
    end
  end

  # one or two points fit exactly whatever they are: only three or more have a margin to give
  defp points_words(1, _), do: "1 point"
  defp points_words(n, rms) when n >= 3 and is_number(rms), do: "#{n} points agree to #{Float.round(rms / 1, 1)}′"
  defp points_words(n, _), do: "#{n} points"

  defp ago(%DateTime{} = at, %DateTime{} = now), do: Controller.Components.Pictures.ago(max(DateTime.diff(now, at), 0))
  defp ago(_, _), do: "earlier"
end
