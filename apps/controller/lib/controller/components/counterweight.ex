defmodule Controller.Components.Counterweight do
  @moduledoc """
  The one thing about a German equatorial mount the sky cannot say: which
  side its counterweight is on. Both sides of the mount see the same stars,
  so an alignment only ever guesses it, and a mount whose home was never set
  picks its side of the pier for every Go To by it. Twice the guess was
  upside down, so on such a mount Go To and tracking wait until someone says
  (`Controller.Sky.Pointing.side_guessed?/2`, #113). The page asks, in words
  someone standing at the mount in the dark can answer by looking at it, and
  `Controller.Sky.Lineup.set_counterweight/3` keeps the answer with the
  alignment.

    * `card/1`: the question, two keys in a radio group for how the mount
      stands right now. Once told, the same card is the fact: the key the
      model now has is lit, and a tap on the other one changes it. On Setup
      (`/setup/<mount>#counterweight`, where every mode points), on Align by
      Phone Photo and under Align with the Camera, where a mount with no home
      gets its alignment, and wherever a Go To was refused for want of it.
    * `line/1`: "Counterweight side: guessed. Tell it ›", wherever a pose is
      chosen on the guess.
    * `asking/2`: the question while it is still open, for a page that asks it
      only after a Go To waited for it.
    * `answer/3`: a tap on one of the keys, for the page's event.
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

  defp detail(%{from: :guessed}), do: "Guessed so far, from where the alignment points were taken. Go To and tracking wait for an answer."
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
  The question while it is still open: `Lineup.counterweight/2` for `model`
  and `snap` while the side is guessed, nil once told or with nothing resting
  on it, so a card drawn with it goes away once anyone answers.
  """
  def asking(model, snap) do
    case Controller.Sky.Lineup.counterweight(model, snap) do
      %{from: :guessed} = cw -> cw
      _ -> nil
    end
  end

  @doc """
  A tap on one of the card's keys, from a page's `"counterweight"` event:
  tells mount `id` (as it stands in `snap`) where the counterweight is, and
  returns `{told?, words}`, whether it took and the notice to show.
  """
  def answer(id, snap, where) when where in ["below", "above"] do
    where = String.to_existing_atom(where)
    result = Controller.Sky.Lineup.set_counterweight(id, snap, where)
    {match?({:ok, _}, result), words(result, where)}
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
