defmodule Controller.Components.Pictures do
  @moduledoc """
  What the camera on the telescope last saw, and where each picture's plate
  solve stands. One camera is one of these whether its frames come thirty a
  second or one in three minutes: the page always shows the latest picture,
  and once frames are seconds apart it says how long ago that one was taken.

    * `latest/1`: the stills camera's latest picture with its age and what was
      measured in it ("Taken 14 s ago · 40 stars · star size 5.4 arcsec"). While the
      next one is on its way it says so and keeps showing this one.
    * `taking/1`: the picture being taken, stage by stage: preparing, the
      exposure against the shutter time (a bar as well as words), the camera
      finishing it, each file coming down, saving, measuring. Whatever stages
      the camera's driver reports (`Camera.capture/2`); one that reports none
      just says a picture is being taken.
    * `solves/1`: one row per picture in the plate solver's queue, newest
      first: the stage it is at, the seconds used of the seconds it may take
      (a bar as well as words), or how it ended.
    * `ago/1`, `age_words/2`: the age in words, for a line of a page's own.

  A page that draws these keeps its own clock (`now_ms`, wall time in
  milliseconds, refreshed each second) so the ages and the bars move.
  """
  use Phoenix.Component
  use Controller, :verified_routes

  import Controller.Components.UI, only: [item: 1, items: 1]

  @doc "The stills camera's latest picture, how long ago it was taken, and what was measured in it."
  attr :last, :map, default: nil, doc: "`Controller.StillCamera.status().last`"
  attr :now_ms, :integer, required: true
  attr :busy, :boolean, default: false, doc: "the shutter is open or the picture is on its way"
  attr :shot, :map, default: nil, doc: "`Controller.StillCamera.status().shot`: the picture being taken, stage by stage"
  attr :empty, :string, default: "No picture yet"

  def latest(assigns) do
    ~H"""
    <section class="scope-frame" aria-label="latest picture">
      <img :if={picture?(@last)} src={~p"/cameras/stills/latest.png?#{[t: @last.seq]}"} alt={"Latest picture, taken #{age_words(@last, @now_ms)}"} />
      <div :if={!picture?(@last)} class="scope-frame-empty"><p class="dim">{if @busy, do: "Taking a picture", else: @empty}</p></div>
      <%!-- only the facts are a live region: an age that counts up would be read out every second --%>
      <p :if={picture?(@last)} class="dim">
        <span>Taken {age_words(@last, @now_ms)}</span><span :if={facts(@last) != ""}> · </span><span role="status">{facts(@last)}</span>
      </p>
      <.taking :if={@busy} shot={@shot} now_ms={@now_ms} />
    </section>
    """
  end

  @doc """
  The picture being taken: its stage in words, and while the shutter is open
  how much of the exposure has gone, as a bar and in seconds.
  """
  attr :shot, :map, default: nil
  attr :now_ms, :integer, required: true

  def taking(assigns) do
    ~H"""
    <p class="shot-now">
      <span role="status">{shot_words(@shot)}</span><span :if={timed?(@shot)}> · {exposed_s(@shot, @now_ms)} s of {exposure_s(@shot)}</span>
      <progress :if={timed?(@shot)} max={exposure_s(@shot)} value={exposed_s(@shot, @now_ms)} aria-label="exposure"></progress>
    </p>
    """
  end

  @doc "A capture's stage in words (`Controller.StillCamera.status().shot`)."
  def shot_words(%{stage: :preparing}), do: "Preparing the camera"
  def shot_words(%{stage: :exposing}), do: "Exposing"
  def shot_words(%{stage: :processing}), do: "The camera is finishing the picture"
  def shot_words(%{stage: :downloading, name: name} = s) when is_binary(name), do: "Downloading #{name}#{size_words(s[:bytes])}"
  def shot_words(%{stage: :downloading}), do: "Downloading the picture"
  def shot_words(%{stage: :saving}), do: "Saving the files"
  def shot_words(%{stage: :measuring}), do: "Measuring the stars"
  def shot_words(_), do: "Taking a picture"

  defp size_words(b) when is_integer(b) and b >= 1_000_000, do: " · #{Float.round(b / 1_000_000, 1)} MB"
  defp size_words(b) when is_integer(b) and b > 0, do: " · #{div(b, 1000)} kB"
  defp size_words(_), do: ""

  # an exposure of two seconds or more has something to count; a shorter one is over before it shows
  defp timed?(%{stage: :exposing, exposure_ms: ms, since_ms: since}) when is_number(ms) and is_integer(since), do: ms >= 2_000
  defp timed?(_), do: false

  defp exposure_s(%{exposure_ms: ms}), do: round(ms / 1000)
  defp exposed_s(%{since_ms: since} = shot, now_ms), do: (now_ms - since) |> div(1000) |> max(0) |> min(exposure_s(shot))

  defp picture?(last), do: is_map(last) and last[:w] != nil

  @doc "Every picture in the solver's queue, newest first: where its solve is, or how it ended."
  attr :plates, :list, required: true, doc: "`Controller.Plates.view(mount).plates`"
  attr :now_ms, :integer, required: true

  def solves(assigns) do
    ~H"""
    <.items label="pictures">
      <.item :for={p <- @plates} as="li" label={"Picture #{p.n}"} detail={solve_words(p, @now_ms)}>
        <progress :if={p.state == :solving} max={solve_limit(p)} value={solve_used(p, @now_ms)} aria-label={"Picture #{p.n}: time used"}></progress>
      </.item>
    </.items>
    """
  end

  # "40 stars · star size 5.4 arcsec"
  defp facts(last) do
    [
      is_integer(last[:stars]) && "#{last.stars} #{if last.stars == 1, do: "star", else: "stars"}",
      match?(%{arcsec: a} when is_number(a), last[:star_size]) && "star size #{Float.round(last.star_size.arcsec / 1, 1)} arcsec"
    ]
    |> Enum.filter(& &1)
    |> Enum.join(" · ")
  end

  @doc "How long ago a record with an `:at` was made, in words."
  def age_words(%{at: %DateTime{} = at}, now_ms) do
    s = div(now_ms - DateTime.to_unix(at, :millisecond), 1000)
    # past a minute the age alone is vague: the clock time goes with it
    if s >= 60, do: "#{ago(s)}, at #{Calendar.strftime(at, "%H:%M:%S")} UTC", else: ago(s)
  end

  def age_words(_, _), do: "at an unknown time"

  @doc "Seconds as an age: \"just now\", \"14 s ago\", \"3 min ago\", \"2 h ago\"."
  def ago(s) when s < 5, do: "just now"
  def ago(s) when s < 90, do: "#{s} s ago"
  def ago(s) when s < 5400, do: "#{div(s, 60)} min ago"
  def ago(s), do: "#{div(s, 3600)} h ago"

  # -- one picture's solve, in words ---------------------------------------------------------

  @doc "One plate's line: its stage and time while solving, the answer once solved, the reason if not."
  def solve_words(%{state: :solved, solution: sol}, _now) when is_map(sol) do
    ["Solved", is_number(sol[:seconds]) && "in #{round(sol.seconds)} s", is_integer(sol[:stars]) && "#{sol.stars} stars"] |> Enum.filter(& &1) |> Enum.join(" · ")
  end

  def solve_words(%{state: :queued}, _now), do: "Waiting for the solver"

  def solve_words(%{state: :solving, solving: %{} = sv} = p, now) do
    used = solve_used(p, now)
    "#{stage_words(sv)} · #{used} s of up to #{solve_limit(p)}"
  end

  def solve_words(%{state: :solving}, _now), do: "Solving"
  def solve_words(%{state: :failed, reason: why}, _now), do: "No match: " <> why_words(why)
  def solve_words(_, _now), do: ""

  defp stage_words(%{stage: :reading}), do: "Reading the picture"
  defp stage_words(%{stage: :stars, stars: n}) when is_integer(n), do: "Found #{n} stars"
  defp stage_words(%{stage: :matching, how: :hinted, stars: n}), do: "#{stars(n)}Matching near where the mount thinks it points"
  defp stage_words(%{stage: :matching, stars: n}), do: "#{stars(n)}Matching against the whole sky"
  defp stage_words(_), do: "Solving"

  defp stars(n) when is_integer(n), do: "#{n} stars. "
  defp stars(_), do: ""

  @doc "Why a picture was not solved, in words."
  def why_words("moving"), do: "the telescope was moving"
  def why_words("deadline"), do: "it ran out of time"
  def why_words("timeout"), do: "it ran out of time"
  def why_words("too_few_stars"), do: "too few stars (a tree, cloud, or the focus)"
  def why_words("no_solution"), do: "the stars did not match the sky"
  def why_words("below_horizon"), do: "it solved below the horizon (check Location)"
  def why_words("no_solver"), do: "no plate solver on this box"
  def why_words(other), do: other |> to_string() |> String.replace("_", " ")

  # seconds this solve has used, and the most it may: the bar's value and its max
  defp solve_used(%{solving: %{since_ms: since}}, now) when is_integer(since), do: max(div(now - since, 1000), 0)
  defp solve_used(_, _), do: 0

  defp solve_limit(%{solving: %{total_ms: total}}) when is_integer(total), do: max(div(total, 1000), 1)
  defp solve_limit(_), do: 120
end
