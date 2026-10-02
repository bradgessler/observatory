defmodule Controller.ScopeCameraFocusLive do
  @moduledoc """
  Focusing by hand: turn the focuser slowly and watch. Nothing to tap.

  **The picture comes first**, with what the camera made of it drawn over
  it: a ring round each star it measured, a small × on each speck it threw
  out (a hot pixel, noise), and a dashed line inside the edge it ignores
  (half a star off the edge, and the corners a camera lifts to correct its
  lens). So it's plain whether it's seeing anything real. A dot in its
  corner pulses with each new picture: that's the rhythm to step to.

  **Sharpness** is two things added: how much crisp detail the picture
  holds (`Controller.ScopeCamera.Image.detail/2`: steps in brightness
  between neighbouring pixels bigger than noise; it peaks at focus for
  anything with edges, but only rises once focus is close), and, when stars
  are in view in at least 2 of the last 3 pictures, 2 over their size (the
  half-flux radius), which moves from far out, as their discs shrink. Both
  rise as focus improves. It's judged against your own range, from the
  blurriest to the sharpest since the page opened, so a constant (hot
  pixels, glow) cancels out and no number needs explaining: the advice says
  which way to turn, and a line of the last two minutes (up is sharper, the
  sharpest ringed) shows how you got there. Until something in the picture
  changes with focus there's no line, only a calm sentence in its place.

  **The telescope moving** smears every picture, so while it moves (and for
  one picture's light after) readings pause: those pictures aren't judged,
  the line leaves a shaded gap, and the advice says so.

  **Timing.** A step shows up about one exposure, plus the measuring, after
  it's made; the bottom line says how long, so a rhythm is easy: step,
  count, look.

  Every box has a fixed size, and what changes every picture (the frame
  number, the stars' size) sits at the bottom: the words change, the layout
  never moves.
  """
  use Controller, :live_view
  import Controller.Components.UI
  import Controller.Components.Charts

  alias Controller.{ScopeCamera, Settings}

  # pictures in the line (two minutes at one a second)
  @keep 120
  # a change smaller than this share of the range is the same, within the measurement's wobble
  @same 0.08

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      ScopeCamera.subscribe()
      Settings.subscribe()
      # focusing needs pictures coming
      ScopeCamera.live(true, ScopeCamera.find()[:node] || node())
    end

    cam = ScopeCamera.find()

    {:ok,
     assign(socket,
       page_title: "Telescope Camera · Focus",
       night: Settings.get("night", false),
       cam: cam,
       latest: latest(cam),
       samples: [],
       moved_at: nil
     )}
  end

  @impl true
  def handle_info({:scope_camera, heard}, socket) do
    cam = ScopeCamera.prefer(socket.assigns.cam, heard)
    latest = latest(cam)
    socket = if moving?(), do: assign(socket, moved_at: System.monotonic_time(:millisecond)), else: socket
    {:noreply, socket |> assign(cam: cam, latest: latest) |> sample(latest)}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info(_, socket), do: {:noreply, socket}

  @impl true
  def handle_event("start_over", _, socket), do: {:noreply, assign(socket, samples: [])}

  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  defp latest(cam), do: List.first(cam[:frames] || [])

  # each new picture once: its detail, steadied over the last three (a blip isn't a change)
  defp sample(socket, %{seq: seq, ok: true} = r) do
    case socket.assigns.samples do
      [%{seq: ^seq} | _] ->
        socket

      samples ->
        if smeared?(socket.assigns.moved_at, r) do
          # light gathered while the telescope moved: kept as a gap, not judged
          assign(socket, samples: Enum.take([%{seq: seq, at: r.at, moving: true} | samples], @keep))
        else
          still = Enum.reject(samples, & &1[:moving])
          steady = steady_hfr(r, still)
          # far from focus the stars' size moves (their discs shrink); near it, the detail does
          raw = (r[:detail] || 0.0) + if(steady, do: 2 / steady, else: 0.0)
          recent = [raw | still |> Enum.take(2) |> Enum.map(& &1.raw)] |> Enum.sort()
          s = %{seq: seq, at: r.at, raw: raw, raw_hfr: hfr(r), detail: Enum.at(recent, div(length(recent), 2)), hfr: steady}
          assign(socket, samples: Enum.take([s | samples], @keep))
        end
    end
  end

  defp sample(socket, _), do: socket

  # the mount moved while this picture's light came in (or a moment before: its light, plus a second)
  defp smeared?(nil, _), do: false

  defp smeared?(moved_at, r) do
    light = round((r[:exposure_ms] || 0) * (r[:stack] || 1))
    System.monotonic_time(:millisecond) - moved_at < light + 1_000
  end

  # any mount on this machine slewing or going to (tracking is slow enough not to smear)
  defp moving? do
    Enum.any?(Mount.list(), fn m ->
      Mount.snapshot(m).axes |> Map.values() |> Enum.any?(&(&1[:goto_pending] || (&1[:running] && abs(&1[:deg_per_s] || 0) > 0.01)))
    end)
  catch
    _, _ -> false
  end

  # star size only when 2 of the last 3 pictures had stars
  defp steady_hfr(r, samples) do
    raw = [hfr(r) | samples |> Enum.take(2) |> Enum.map(& &1[:raw_hfr])] |> Enum.filter(& &1) |> Enum.sort()
    if length(raw) >= 2, do: Enum.at(raw, div(length(raw), 2))
  end

  defp hfr(%{stars: n, hfr_px: h}) when is_integer(n) and n > 0 and is_number(h), do: h
  defp hfr(_), do: nil

  # -- reading the samples --------------------------------------------------------------------

  # the range so far: from the blurriest to the sharpest steadied reading
  defp range(samples) do
    d = for %{detail: v} <- samples, do: v
    {Enum.min(d, fn -> 0.0 end), Enum.max(d, fn -> 0.0 end)}
  end

  # something in the picture is changing with focus: the range is more than wobble
  defp signal?({lo, hi}), do: hi - lo > max(0.25 * max(lo, 0.0), 0.5)

  defp share(v, {lo, hi}) when hi > lo, do: (v - lo) / (hi - lo)
  defp share(_, _), do: nil

  # newest first
  defp verdict([]), do: {"Turn the focuser slowly and watch the picture.", nil}
  defp verdict([%{moving: true} | _]), do: {"The telescope is moving, so the frames are smeared. Readings pause until it stops.", nil}

  defp verdict(all) do
    samples = Enum.reject(all, & &1[:moving])
    verdict_still(samples)
  end

  defp verdict_still([]), do: {"Turn the focuser slowly and watch the picture.", nil}

  defp verdict_still([now | _] = samples) do
    r = range(samples)
    before = Enum.at(samples, 3)
    best = Enum.max_by(samples, & &1.detail)

    cond do
      not signal?(r) ->
        {"Nothing in the picture is getting sharper or blurrier yet. Keep turning, or point at something bright.", nil}

      best.seq != now.seq and share(now.detail, r) < 1 - 2 * @same and DateTime.diff(now.at, best.at) >= 3 ->
        {"You've passed the sharpest point (#{ago(best, now)}). Turn back a little.", :worse}

      share(now.detail, r) >= 1 - @same ->
        {"At the sharpest so far. Small turns either way to make sure.", :better}

      before && share(now.detail, r) - share(before.detail, r) > @same ->
        {"Getting sharper. Keep turning the same way, slowly.", :better}

      before && share(before.detail, r) - share(now.detail, r) > @same ->
        {"Getting blurrier. Turn the other way.", :worse}

      true ->
        {"About the same. Keep turning slowly.", nil}
    end
  end

  defp ago(%{at: then}, %{at: now}) do
    case DateTime.diff(now, then) do
      s when s < 90 -> "#{s} s ago"
      s -> "#{div(s, 60)} min ago"
    end
  end

  # only when there's something to say: stars, and their size against sharp here
  defp stars_line([%{hfr: h} | _]) when is_number(h), do: "Stars measure #{fmt(h)} px half-flux radius (half their light falls inside it); about 1.5 is as sharp as these optics get."
  defp stars_line(_), do: nil

  defp fmt(h), do: :erlang.float_to_binary(h * 1.0, decimals: 1)

  @doc false
  # How long after a step a picture shows it: the light of a whole picture
  # taken after the step (exposure x frames averaged), plus measuring it,
  # plus the trip to the phone; and at worst one more exposure, when the
  # step lands while a picture is already collecting light.
  def latency(%{} = r) do
    light = round((r[:exposure_ms] || 0) * (r[:stack] || 1))
    typical = light + (r[:measure_ms] || 500) + 200
    {typical, typical + round(r[:exposure_ms] || 0)}
  end

  def latency(_), do: nil

  defp rhythm(r) do
    case latency(r) do
      {typical, worst} -> "Frame #{r.seq} · a step shows up about #{secs(typical)} later: step, count #{max(round(worst / 1000), 1)}, look."
      nil -> "Waiting for the first frame."
    end
  end

  defp secs(ms), do: "#{:erlang.float_to_binary(ms / 1000, decimals: 1)} s"

  @impl true
  def render(assigns) do
    {say, tone} = verdict(assigns.samples)
    still = Enum.reject(assigns.samples, & &1[:moving])
    r = range(still)
    oldest_first = Enum.reverse(assigns.samples)
    line = if signal?(r), do: Enum.map(oldest_first, &(&1[:detail] && share(&1.detail, r))), else: []
    marks = assigns.latest && assigns.latest[:marks]

    assigns =
      assign(assigns,
        say: say,
        tone: tone,
        line: line,
        bands: if(line != [], do: bands(oldest_first), else: []),
        # the line fills the width from the start, so a few pictures aren't a dot in the corner
        slots: min(max(length(line), 20), @keep),
        since: since(oldest_first),
        marks: marks,
        stars_line: stars_line(still)
      )

    ~H"""
    <.page id="scope-camera-focus" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/telescope"} label="Telescope Camera" />
        <.title>Focus</.title>
        <.actions><.help href={~p"/docs/scope-camera#focus-it"} label="focusing" /><.stop /></.actions>
      </:header>

      <.split>
        <:main>
          <%!-- the picture and what was made of it; its space is kept before it arrives --%>
          <section class="focus-pic" aria-label="latest picture">
            <img :if={@latest && @latest[:ok] != false} src={ScopeCamera.src(@cam, @latest.seq)} alt={"Latest frame, #{@latest.seq}"} />
            <div :if={!(@latest && @latest[:ok] != false)} class="focus-pic-empty" aria-hidden="true"></div>
            <svg :if={@marks} class="focus-overlay" viewBox={"0 0 #{@latest[:w] || 960} #{@latest[:h] || 540}"} preserveAspectRatio="none" aria-hidden="true">
              <rect x={@marks.border} y={@marks.border} width={(@latest[:w] || 960) - 2 * @marks.border} height={(@latest[:h] || 540) - 2 * @marks.border} class="ov-border" />
              <g :for={m <- @marks.rejected} class="ov-speck"><line x1={m.x - 5} y1={m.y - 5} x2={m.x + 5} y2={m.y + 5} /><line x1={m.x - 5} y1={m.y + 5} x2={m.x + 5} y2={m.y - 5} /></g>
              <circle :for={m <- @marks.stars} cx={m.x} cy={m.y} r="12" class="ov-star" />
            </svg>
            <%!-- a new element each picture, so its one pulse plays again: the rhythm to step to --%>
            <span :if={@latest} id={"pulse-#{@latest.seq}"} class="focus-pulse" aria-hidden="true"></span>
          </section>

          <ul class="focus-legend" aria-label="What the marks mean">
            <li><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" class="ov-star" /></svg>Star, measured</li>
            <li><svg viewBox="0 0 16 16" aria-hidden="true"><g class="ov-speck"><line x1="3" y1="3" x2="13" y2="13" /><line x1="3" y1="13" x2="13" y2="3" /></g></svg>Speck, ignored: a hot pixel or noise</li>
            <li><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="2" y="2" width="12" height="12" class="ov-border" /></svg>Outside the dashes, ignored</li>
          </ul>
        </:main>
        <:side>
          <section class="focus-say" role="status" aria-live="polite">
            <p class={["focus-advice", @tone == :worse && "tone-caution"]}>{@say}</p>
          </section>

          <div class="focus-line">
            <%= if @line != [] do %>
              <span class="focus-axis-top dim">Sharper</span>
              <.sparkline values={@line} points={@slots} min={0} max={1} width={343} height={56} bands={@bands} label={"sharpness since #{@since}, higher is sharper, the sharpest ringed"} class="focus-spark" mark_max />
              <span class="focus-axis-bottom dim">Blurrier</span>
              <p class="dim focus-axis-time"><span>{@since}</span><span :if={@bands != []}>Shaded: telescope moving</span><span>Now</span></p>
            <% else %>
              <p class="dim focus-line-empty">A line of sharper and blurrier starts here once something in the picture changes as you turn.</p>
            <% end %>
          </div>

          <%!-- what changes every picture: at the bottom, in boxes of their own size --%>
          <p class="dim focus-stars">{@stars_line} <.link :if={@stars_line} href={~p"/docs/scope-camera#focus-it"}>What's half-flux radius?</.link></p>
          <p class="dim focus-rhythm">{rhythm(@latest)}</p>

          <.row>
            <.btn phx-click="start_over">Start Over</.btn>
            <.btn navigate={~p"/cameras/telescope/settings"}>Exposure and Gain</.btn>
          </.row>
        </:side>
      </.split>
    </.page>
    """
  end

  # how far back the line goes, in words
  defp since([%{at: first} | _] = oldest_first) do
    %{at: last} = List.last(oldest_first)

    case DateTime.diff(last, first) do
      s when s < 90 -> "#{max(s, 1)} s ago"
      s -> "#{div(s, 60)} min ago"
    end
  end

  defp since(_), do: "Now"

  # runs of pictures taken while the telescope moved, as slot ranges in the line (oldest first)
  defp bands(oldest_first) do
    oldest_first
    |> Enum.with_index()
    |> Enum.chunk_by(fn {s, _} -> s[:moving] == true end)
    |> Enum.filter(fn [{s, _} | _] -> s[:moving] == true end)
    |> Enum.map(fn run -> {elem(hd(run), 1), elem(List.last(run), 1)} end)
  end

end
