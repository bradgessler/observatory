defmodule Controller.SkyAimTest do
  @moduledoc """
  The scope mark on the sky map and how far off it may be: a ring true to
  size on the sky, and one line that says what the number rests on.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.SkyLive

  test "the margin is the alignment's rms doubled with the tracker's error on top" do
    assert {:margin, a} = SkyLive.aim(%{solved?: true, n: 3, rms_arcmin: 7.0}, %{error_arcmin: 0.4})
    assert_in_delta a.margin, :math.sqrt(14.0 * 14.0 + 0.4 * 0.4), 1.0e-9
    assert SkyLive.aim_words({:margin, a}) == "Crosshair ±14′ · 3 alignment points agree to 7.0′ · tracking 0.4′"

    # no tracker running: just the alignment
    assert {:margin, %{margin: 14.0, tracking: +0.0}} = SkyLive.aim(%{solved?: true, n: 5, rms_arcmin: 7.0}, nil)

    # a degree or more reads in degrees
    assert SkyLive.aim_words({:margin, %{margin: 95.0, rms: 47.5, n: 3, tracking: 0.0}}) =~ "±1.6°"
  end

  test "fewer than three points, or none, and it says so instead of drawing a number" do
    assert SkyLive.aim(%{solved?: true, n: 2, rms_arcmin: 0.0}, nil) == {:unknown, 2}
    assert SkyLive.aim_words({:unknown, 2}) =~ "margin unknown until a third alignment point"
    assert SkyLive.aim(%{solved?: false, n: 0, rms_arcmin: nil}, nil) == :assumed
    assert SkyLive.aim(nil, nil) == :assumed
    assert SkyLive.aim_words(:assumed) =~ "assumes a polar-aligned mount"
  end

  test "the ring is true to size on the sky" do
    # at the zenith a 10° ring is a circle of radius tan(5°) in map units (×100)
    for pt <- String.split(SkyLive.margin_ring(90.0, 0.0, 10.0), " ") do
      [x, y] = pt |> String.split(",") |> Enum.map(&String.to_float/1)
      assert_in_delta :math.sqrt(x * x + y * y), 100 * :math.tan(5 * :math.pi() / 180), 0.01
    end

    # 30 points, all around the mark, low in the east
    pts = SkyLive.margin_ring(30.0, 90.0, 1.0) |> String.split(" ")
    assert length(pts) == 30
    {cx, cy} = Controller.Sky.Astro.project(30.0, 90.0)
    xs = Enum.map(pts, &(&1 |> String.split(",") |> hd() |> String.to_float()))
    assert Enum.min(xs) < cx * 100 and Enum.max(xs) > cx * 100
    assert cy * 100 |> abs() < 1.0
  end

  test "a zeroed mount shows the mark and says it assumes a polar-aligned mount", %{conn: conn} do
    id = "sim-aim-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000

    {:ok, _view, html} = live(conn, "/sky/#{id}")
    refute html =~ "Crosshair"

    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/sky/#{id}")
    html = render(view)
    assert html =~ ~s(class="scope")
    assert html =~ "Crosshair assumes a polar-aligned mount"
    # no measured margin, so no ring
    refute html =~ ~s(class="aim")
  end
end
