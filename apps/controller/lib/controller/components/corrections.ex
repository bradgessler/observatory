defmodule Controller.Components.Corrections do
  @moduledoc """
  What the software is correcting for, drawn rather than described: the law
  in charge (three keys, one lit), a target with the true pole at the centre
  and a dot where this mount's polar axis really points, the encoder offsets,
  and two bars for how much authority the tracker is using on each axis
  right now (sidereal is 1× on RA and 0 on Dec for a perfect set-up; a mount
  set down anyhow needs both).

      <.corrections law={3} status={status} model={model} lat={lat} tracker={tracker} />
  """
  use Phoenix.Component

  alias Controller.Sky.{Astro, Model}

  attr :law, :integer, required: true
  attr :status, :map, default: nil, doc: "Controller.Sky.Lineup.status/1"
  attr :model, :map, default: nil, doc: "Controller.Sky.Lineup.model/1"
  attr :lat, :float, required: true
  attr :tracker, :map, default: nil, doc: "Controller.Sky.Tracker.status/1"
  attr :offset, :map, default: %{"ra" => 0.0, "dec" => 0.0}, doc: "the one-star sync offset (law 2)"
  attr :compact, :boolean, default: false

  def corrections(assigns) do
    assigns = assign(assigns, pole: pole(assigns.model, assigns.lat), size: if(assigns.compact, do: 120, else: 160))

    ~H"""
    <div class={["corr", @compact && "compact"]}>
      <ol class="laws" aria-label="control law in charge">
        <li :for={{n, words} <- [{1, "Axes"}, {2, "Ideal Sky"}, {3, "This Mount"}]} class={["law-key", n == @law && "on"]} aria-current={if n == @law, do: "true"}>
          <b>{n}</b> {words}<span :if={n == @law} class="sr-only"> (in charge)</span>
        </li>
      </ol>

      <div class="corr-body">
        <svg class="corr-target" viewBox="-100 -100 200 200" width={@size} height={@size} role="img" aria-label={if @model, do: "the mount's polar axis is #{fmt(@pole.off)}° from the pole, on a #{fmt(@pole.scale)}° target", else: "polar axis assumed on the pole"}>
          <circle :for={f <- [1 / 3, 2 / 3, 1.0]} class="ring" r={f * 88} />
          <line class="hair" x1="-96" y1="0" x2="96" y2="0" />
          <line class="hair" x1="0" y1="-96" x2="0" y2="96" />
          <text class="lbl" x="92" y="-4" text-anchor="end">E</text>
          <text class="lbl" x="4" y="-90">up</text>
          <text class="lbl scale" x="-96" y="96">{fmt(@pole.scale)}°</text>
          <%= if @pole.dot do %>
            <line class="lead" x1="0" y1="0" x2={elem(@pole.dot, 0)} y2={elem(@pole.dot, 1)} />
            <circle class="axis" cx={elem(@pole.dot, 0)} cy={elem(@pole.dot, 1)} r="6" />
          <% end %>
          <circle class="pole" r="3" />
        </svg>

        <div class="corr-text">
          <div class="state-line">
            <strong :if={@model}>Polar axis {fmt(@pole.off)}° from the pole</strong>
            <strong :if={!@model}>Polar axis assumed on the pole</strong>
            <span :if={@model} class="dim">{fmt(abs(@pole.east))}° {if @pole.east >= 0, do: "east", else: "west"} · {fmt(abs(@pole.up))}° too {if @pole.up >= 0, do: "steep", else: "shallow"}</span>
            <span :if={!@model and (abs(@offset["ra"]) > 0.01 or abs(@offset["dec"]) > 0.01)} class="dim">No stars yet; one sync offset in force</span>
            <span :if={!@model and abs(@offset["ra"]) <= 0.01 and abs(@offset["dec"]) <= 0.01} class="dim">No stars yet; no correction in force</span>
          </div>
          <div class="kv"><span class="kv-k">offsets</span><span class="kv-v">RA {sgn(off(@model, @offset, :ra))}° · Dec {sgn(off(@model, @offset, :dec))}°</span></div>
          <div :if={@status && @status.n > 0} class="kv"><span class="kv-k">stars</span><span class="kv-v">{@status.n}{if @status.rms_arcmin && @status.n >= 3, do: " · agree to #{fmt(@status.rms_arcmin)}′", else: ""}</span></div>
        </div>
      </div>

      <div class="auth" role="group" aria-label="tracking authority in use">
        <.bar label="RA" rate={@tracker && @tracker.ra_rate} tick={1.0} />
        <.bar label="Dec" rate={@tracker && @tracker.dec_rate} tick={0.0} />
        <span class="dim auth-note">
          {cond do
            @tracker && @tracker.paused == :goto -> "Holding #{@tracker.name} · slewing"
            @tracker && @tracker.paused -> "Holding #{@tracker.name} · paused while a hand is on a control"
            @tracker -> "holding #{@tracker.name}#{if @tracker.error_arcmin, do: " · #{fmt(@tracker.error_arcmin)}′ off", else: ""}"
            true -> "Not holding anything · sidereal would be RA 1×, Dec 0"
          end}
        </span>
      </div>
    </div>
    """
  end

  # a rate bar: zero in the middle, ±2× full scale, a tick where a perfect mount would sit
  attr :label, :string, required: true
  attr :rate, :float, default: nil
  attr :tick, :float, required: true
  @scale 2.0

  defp bar(assigns) do
    assigns = assign(assigns, pct: pct(assigns.rate), tick_pct: pct(assigns.tick), over: assigns.rate && abs(assigns.rate) > @scale)

    ~H"""
    <div class="auth-row">
      <span class="auth-k">{@label}</span>
      <span class="auth-track" aria-hidden="true">
        <i class="auth-tick" style={"left: #{@tick_pct}%"}></i>
        <i :if={@rate} class="auth-fill" style={fill_style(@pct)}></i>
      </span>
      <span class="auth-v">{if @rate, do: "#{sgn(@rate)}×#{if @over, do: " ▸", else: ""}", else: "—"}</span>
    </div>
    """
  end

  defp pct(nil), do: 50.0
  defp pct(rate), do: 50.0 + (rate |> max(-@scale) |> min(@scale)) / @scale * 50.0

  defp fill_style(pct) when pct >= 50.0, do: "left: 50%; width: #{pct - 50.0}%"
  defp fill_style(pct), do: "left: #{pct}%; width: #{50.0 - pct}%"

  # the fitted axis relative to the ideal one, in degrees east and up, and the
  # target's scale (the outer ring), picked so the dot is always inside
  defp pole(nil, _lat), do: %{dot: nil, east: 0.0, up: 0.0, off: 0.0, scale: 5.0}

  defp pole(m, lat) do
    ideal = Model.ideal(lat)
    east = Astro.norm180(m.axis_az - ideal.axis_az) * :math.cos(ideal.axis_alt * :math.pi() / 180)
    up = m.axis_alt - ideal.axis_alt
    off = :math.sqrt(east * east + up * up)
    scale = Enum.find([1.0, 2.0, 5.0, 10.0, 20.0, 45.0, 90.0], 180.0, &(&1 >= off * 1.15))
    k = 88 / scale
    %{dot: {east * k, -up * k}, east: east, up: up, off: off, scale: scale}
  end

  defp off(nil, offset, :ra), do: offset["ra"]
  defp off(nil, offset, :dec), do: offset["dec"]
  defp off(m, _, :ra), do: m.off_ra
  defp off(m, _, :dec), do: m.off_dec

  defp fmt(nil), do: "—"
  defp fmt(x), do: :erlang.float_to_binary(x / 1, decimals: 1)
  defp sgn(x) when x >= 0, do: "+" <> fmt(x)
  defp sgn(x), do: "−" <> fmt(abs(x))
end
