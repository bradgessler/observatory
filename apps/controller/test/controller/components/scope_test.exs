defmodule Controller.Components.ScopeTest do
  @moduledoc """
  The mount is drawn in 3-D, posed by the encoders: the tube's direction
  follows Dec, the head follows RA. The pose is checked on the model's own
  axes as they land on the screen (`Scope.skeleton/1`), the drawing on its
  shaded faces.
  """
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

  defp dir({{x1, y1}, {x2, y2}}) do
    {x, y} = {x2 - x1, y2 - y1}
    n = :math.sqrt(x * x + y * y)
    {x / n, y / n}
  end

  defp tube_dir(pose), do: dir(Scope.skeleton(pose).tube)
  defp polar_dir(pose), do: dir(Scope.skeleton(pose).polar)

  defp parallel?({ax, ay}, {bx, by}), do: abs(abs(ax * bx + ay * by) - 1.0) < 0.02

  test "at Dec 0 the tube lies along the polar axis" do
    pose = eq(0.0, 0.0)
    assert parallel?(tube_dir(pose), polar_dir(pose))
  end

  # perpendicularity in space does not survive a projection, but turning the
  # tube through half a circle must put it back along the polar axis the
  # other way round, and that does survive: it is the same 3-D property.
  test "at Dec 180 the tube lies along the polar axis, pointing the other way" do
    pose = eq(0.0, 180.0)
    {tx, ty} = tube_dir(pose)
    {px, py} = polar_dir(pose)
    assert parallel?({tx, ty}, {px, py})
    assert tx * px + ty * py < 0, "the tube should point back down the axis"
  end

  test "at Dec 90 the tube is neither along the axis nor back down it" do
    pose = eq(0.0, 90.0)
    refute parallel?(tube_dir(pose), polar_dir(pose))
  end

  test "turning RA swings the tube to a different place on the screen" do
    refute parallel?(tube_dir(eq(0.0, 60.0)), tube_dir(eq(90.0, 60.0)))
  end

  test "an alt-az pose draws a tube that rises with altitude" do
    low = %{kind: :altaz, az_deg: 180.0, alt_deg: 0.0, running: %{}, tracking: :off}
    high = %{low | alt_deg: 90.0}
    refute parallel?(tube_dir(low), tube_dir(high))
    assert render_component(&Scope.scope/1, pose: high) =~ "alt-az mount"
  end

  # the numbers are where the two axes stand (Dec axis 0 is the tube along the polar axis), and
  # are called that: "RA 12°, Dec -45°" read as a place on the sky, which they are not
  test "it is a labelled image with the axis angles in the label, each called an axis" do
    html = draw(eq(12.0, -45.0, tracking: :model))
    assert html =~ ~s(role="img")
    assert html =~ "RA axis 12°, Dec axis -45°"
    assert html =~ "tracking"
  end

  test "it is solid: shaded faces of the tube, the mount and the legs, lit unevenly, the lens dark" do
    html = draw(eq(30.0, 50.0))
    for m <- ~w(m-tube m-metal m-dark m-leg), do: assert(html =~ m, m)
    levels = Regex.scan(~r/class="m-tube l(\d)"/, html) |> Enum.map(&List.last/1) |> Enum.uniq()
    assert length(levels) >= 3, "the tube should be lit on one side and in shadow on the other"
  end

  test "a running axis draws its motion arc; a still one does not" do
    assert draw(eq(0.0, 30.0, running: %{ra: true, dec: false})) =~ "sc-spin-ra"
    refute draw(eq(0.0, 30.0, running: %{ra: false, dec: false})) =~ "sc-spin-ra"
  end

  test "without detail (a badge) it draws fewer faces: no rings, no diagonal" do
    faces = fn html -> length(String.split(html, "<polygon")) - 1 end
    plain = render_component(&Scope.scope/1, pose: eq(0.0, 0.0), detail: false)
    assert faces.(plain) < faces.(draw(eq(0.0, 0.0)))
    assert plain =~ "m-tube"
  end

  # On a card the faces alone can't be seen (dark shades on a dark ground), so the whole shape is
  # drawn once more under them for the stylesheet to stroke: a rim round the outside.
  test "with an outline it draws every face once more, as one path, before the faces" do
    pose = eq(40.0, 20.0)
    html = render_component(&Scope.scope/1, pose: pose, detail: false, outline: true)
    assert [_, d] = Regex.run(~r/<path d="([^"]+)" class="sc-outline"/, html)
    faces = length(String.split(html, "<polygon")) - 1
    assert length(String.split(d, "Z", trim: true)) == faces
    assert d =~ ~r/^M-?[\d.]+,-?[\d.]+L/
    # under the faces: it comes first, so they cover all of it but what sticks out
    assert :binary.match(html, "sc-outline") < :binary.match(html, "<polygon")

    refute render_component(&Scope.scope/1, pose: pose, detail: false) =~ "sc-outline"
  end
end
