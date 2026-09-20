defmodule Controller.Components.ScopeTest do
  @moduledoc "The drawing is posed by the encoders: the tube's direction follows Dec, the head follows RA."
  use ExUnit.Case, async: true
  import Phoenix.LiveViewTest

  alias Controller.Components.Scope

  defp eq(ha, dec, opts \\ []) do
    %{
      kind: :equatorial,
      polar_alt: Keyword.get(opts, :alt, 38.0),
      polar_az: Keyword.get(opts, :az, 0.0),
      ha_deg: ha,
      dec_deg: dec,
      running: Keyword.get(opts, :running, %{ra: false, dec: false}),
      tracking: Keyword.get(opts, :tracking, :off)
    }
  end

  defp draw(pose), do: render_component(&Scope.scope/1, pose: pose, label: "test")

  # the tube is the widest stroke; pull its direction out of the markup
  defp tube_dir(html) do
    [_, x1, y1, x2, y2] =
      Regex.run(~r/<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" class="sc-tube"/, html)

    norm({String.to_float(x2) - String.to_float(x1), String.to_float(y2) - String.to_float(y1)})
  end

  defp polar_dir(html) do
    [_, x1, y1, x2, y2] =
      Regex.run(~r/<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" class="sc-ra"/, html)

    norm({String.to_float(x2) - String.to_float(x1), String.to_float(y2) - String.to_float(y1)})
  end

  defp norm({x, y}) do
    n = :math.sqrt(x * x + y * y)
    {x / n, y / n}
  end

  defp parallel?({ax, ay}, {bx, by}), do: abs(abs(ax * bx + ay * by) - 1.0) < 0.02

  test "at Dec 0 the tube lies along the polar axis" do
    html = draw(eq(0.0, 0.0))
    assert parallel?(tube_dir(html), polar_dir(html))
  end

  # perpendicularity in space does not survive a projection, but turning the
  # tube through half a circle must put it back along the polar axis the
  # other way round, and that does survive: it is the same 3-D property.
  test "at Dec 180 the tube lies along the polar axis, pointing the other way" do
    html = draw(eq(0.0, 180.0))
    {tx, ty} = tube_dir(html)
    {px, py} = polar_dir(html)
    assert parallel?({tx, ty}, {px, py})
    assert tx * px + ty * py < 0, "the tube should point back down the axis"
  end

  test "at Dec 90 the tube is neither along the axis nor back down it" do
    html = draw(eq(0.0, 90.0))
    refute parallel?(tube_dir(html), polar_dir(html))
  end

  test "turning RA swings the tube to a different place on the screen" do
    a = tube_dir(draw(eq(0.0, 60.0)))
    b = tube_dir(draw(eq(90.0, 60.0)))
    refute parallel?(a, b)
  end

  test "an alt-az pose draws a tube that rises with altitude" do
    low = render_component(&Scope.scope/1, pose: %{kind: :altaz, az_deg: 180.0, alt_deg: 0.0, running: %{}, tracking: :off})
    high = render_component(&Scope.scope/1, pose: %{kind: :altaz, az_deg: 180.0, alt_deg: 90.0, running: %{}, tracking: :off})
    refute parallel?(tube_dir(low), tube_dir(high))
    assert high =~ "alt-az mount"
  end

  test "it is a labelled image with the numbers in the label" do
    html = draw(eq(12.0, -45.0, tracking: :model))
    assert html =~ ~s(role="img")
    assert html =~ "RA 12°"
    assert html =~ "Dec -45°"
    assert html =~ "tracking"
  end

  test "a running axis draws its motion arc; a still one does not" do
    assert draw(eq(0.0, 30.0, running: %{ra: true, dec: false})) =~ "sc-spin-ra"
    refute draw(eq(0.0, 30.0, running: %{ra: false, dec: false})) =~ "sc-spin-ra"
  end

  test "without detail there are no tripod legs" do
    plain = render_component(&Scope.scope/1, pose: eq(0.0, 0.0), detail: false)
    refute plain =~ "sc-leg"
    assert plain =~ "sc-tube"
  end
end
