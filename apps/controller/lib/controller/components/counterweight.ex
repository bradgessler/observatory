defmodule Controller.Components.Counterweight do
  @moduledoc """
  The one thing about a German equatorial mount the sky cannot say: which
  side its counterweight is on. Both sides of the mount see the same stars,
  so an alignment only ever guesses it, and a mount whose home was never set
  picks its side of the pier for every Go To by that guess. So the page
  asks, in words someone standing at the mount in the dark can answer by
  looking at it, and `Controller.Sky.Lineup.set_counterweight/3` keeps the
  answer with the alignment.

    * `card/1`: the question, two keys in a radio group for how the mount
      stands right now. Once told, the same card is the fact: the key the
      model now has is lit, and a tap on the other one changes it. On Setup
      (`/setup/<mount>#counterweight`, where every mode points) and on Align
      by Photo, where a mount with no home gets its alignment.
    * `line/1`: "Counterweight side: guessed. Tell it ›", wherever a pose is
      chosen on the guess.
    * `words/2`: one line for what `set_counterweight/3` answered.

  `cw` is `Controller.Sky.Lineup.counterweight/2`; nil (no alignment, or home
  is set, so nothing rests on it) draws nothing. The page handles the keys'
  `"counterweight"` event, with `where` "below" or "above".
  """
  use Phoenix.Component
  use Controller, :verified_routes
  # by name, not imported: this module has a card of its own
  alias Controller.Components.UI

  attr :cw, :map, default: nil, doc: "`Lineup.counterweight/2`: `%{from: :told | :guessed, now: :below | :above | :level}`"

  def card(assigns) do
    ~H"""
    <UI.card :if={@cw} id="counterweight" title="Counterweight">
      <:aside><UI.badge on={@cw.from == :told}>{if @cw.from == :told, do: "told", else: "guessed"}</UI.badge></:aside>
      <div class="state-line">
        <strong>{headline(@cw)}</strong>
        <span>{detail(@cw)}</span>
      </div>
      <%!-- a key is lit only on what was told: a guess shown lit would read as a fact --%>
      <UI.seg label="The counterweight is, right now">
        <:opt on={lit?(@cw, :below)} click="counterweight" value={%{where: "below"}} disabled={@cw.now == :level}>Below Level<span :if={lit?(@cw, :below)} aria-hidden="true"> ✓</span></:opt>
        <:opt on={lit?(@cw, :above)} click="counterweight" value={%{where: "above"}} disabled={@cw.now == :level}>Above Level<span :if={lit?(@cw, :above)} aria-hidden="true"> ✓</span></:opt>
      </UI.seg>
      <%!-- near level nobody can say by eye, so the keys are greyed and this says what to do --%>
      <UI.hint :if={@cw.now == :level} role="status">{level_words(@cw)}</UI.hint>
      <UI.hint :if={@cw.now != :level}>
        {if @cw.from == :told, do: "Not what you see at the mount? Tap the other one.", else: "Follow the counterweight shaft from the mount out to the weight: sloping down is below level, sloping up is above."}
        <.link href={~p"/docs/setup#counterweight"}>Why it asks</.link>
      </UI.hint>
    </UI.card>
    """
  end

  defp lit?(%{from: :told, now: now}, where), do: now == where
  defp lit?(_, _), do: false

  defp headline(%{from: :guessed}), do: "Is the counterweight below or above level right now?"
  defp headline(%{now: :below}), do: "Below level right now"
  defp headline(%{now: :above}), do: "Above level right now"
  defp headline(%{now: :level}), do: "Close to level right now"

  defp detail(%{from: :guessed}), do: "Guessed so far, from where the alignment points were taken. Go To picks its side of the pier by it."
  defp detail(%{from: :told}), do: "As told. Go To and the tracking limit go by it until the mount is switched on again."

  defp level_words(%{from: :guessed}), do: "The counterweight shaft is close to level right now, too close to call by eye. Turn the RA axis a little, then answer."
  defp level_words(%{from: :told}), do: "The counterweight shaft is close to level right now. To change what was told, turn the RA axis a little first."

  @doc """
  One calm line where a pose is chosen on a guess, linking to the question.
  `from` is `Lineup.status/1`'s `counterweight`; anything but `:guessed` draws nothing.
  """
  attr :from, :atom, default: nil
  attr :mount, :string, default: nil

  def line(assigns) do
    ~H"""
    <p :if={@from == :guessed and @mount} class="lock-line tone-caution" role="status">
      Counterweight side: guessed. <.link href={~p"/setup/#{@mount}" <> "#counterweight"}>Tell it ›</.link>
    </p>
    """
  end

  @doc """
  What to say after a tap: `result` is what `Lineup.set_counterweight/3`
  returned for `where`. A notice, so no full stop at the end.
  """
  def words({:ok, sign}, where) when is_integer(sign) and where in [:below, :above],
    do: "Told: the counterweight is #{where} level right now. Go To and the tracking limit go by it"

  def words({:ok, sign}, _where) when is_integer(sign), do: "Counterweight side told. Go To and the tracking limit go by it"
  def words({:ok, nil}, _where), do: "Counterweight side back to a guess"
  def words({:error, :level}, _where), do: "The counterweight shaft is close to level right now. Turn the RA axis a little and answer again"
  def words({:error, :upright}, _where), do: "The counterweight shaft is close to upright right now. Say below or above level instead"
  def words({:error, :not_lined_up}, _where), do: "No alignment in force. Add alignment points first, by stars or by photo"
  def words(other, _where), do: Controller.Words.error(other)
end
