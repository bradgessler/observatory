defmodule Controller.Sky.SolvePlatesTest do
  @moduledoc """
  Real solves of synthetic plates: stars from the index files themselves
  (`query-starkd`), projected and drawn in Elixir (`Controller.Test.Plate`),
  handed to solve-field. Run with `mix test --only solver`; skipped cleanly
  on a machine without solve-field or the index files.
  """
  use ExUnit.Case, async: false

  alias Controller.Sky.{Astro, Photo, Solve}
  alias Controller.Sky.Solve.Local
  alias Controller.Test.{Plate, RecordingRunner}

  @moduletag :solver

  # checked when this file compiles, which is when the tests run: a machine
  # without solve-field or the index files skips these, and says why
  unless Plate.available?(), do: @moduletag(skip: "solve-field or the index files in ~/.observatory/astrometry are not here")

  setup_all do
    tmp = Path.join(System.tmp_dir!(), "observatory-plates-#{System.unique_integer([:positive])}")
    File.mkdir_p!(tmp)
    on_exit(fn -> File.rm_rf(tmp) end)
    {:ok, tmp: tmp}
  end

  # M42 and the Sword: plenty of Tycho-2 stars in a degree
  @m42 {83.82, -5.39}

  defp plate(center, opts \\ []) do
    {ra, dec} = center
    fov = Keyword.get(opts, :fov_deg, 1.0)
    stars = Plate.stars(ra, dec, fov * 0.75)
    stars = if n = opts[:keep], do: Enum.take(stars, n), else: stars
    Plate.render(stars, Keyword.put(opts, :center, center))
  end

  defp off_arcsec({ra, dec}, sol), do: Astro.separation_radec(ra, dec, sol.ra_deg, sol.dec_deg) * 3600

  test "a hinted solve finds the centre to a few arcseconds, in seconds", ctx do
    pgm = plate(@m42)
    assert Photo.dimensions(pgm) == {:ok, {800, 600}}
    assert {:ok, sol} = Local.solve(pgm, hint: %{ra_deg: 86.0, dec_deg: -2.0, radius_deg: 10}, tmp_dir: ctx.tmp)
    assert off_arcsec(@m42, sol) < 5, "off by #{off_arcsec(@m42, sol)}″"
    assert_in_delta sol.width_deg, 1.0, 0.01
    assert sol.seconds < 30
  end

  test "blind (no hint, a narrow scale) finds the same centre", ctx do
    pgm = plate(@m42)
    assert {:ok, blind} = Local.solve(pgm, scale: {0.8, 1.25}, tmp_dir: ctx.tmp)
    assert {:ok, hinted} = Local.solve(pgm, scale: {0.8, 1.25}, hint: {84.0, -5.0, 5.0}, tmp_dir: ctx.tmp)
    assert off_arcsec(@m42, blind) < 5
    assert Astro.separation_radec(blind.ra_deg, blind.dec_deg, hinted.ra_deg, hinted.dec_deg) * 3600 < 2
  end

  test "a rotated, mirrored plate elsewhere in the sky solves, and says it is rotated", ctx do
    # the Pleiades, turned 37° and mirrored the way a star diagonal shows them
    center = {56.75, 24.12}
    straight = plate(center, fov_deg: 1.5)
    turned = plate(center, fov_deg: 1.5, rotation_deg: 37, mirror: true)
    assert {:ok, a} = Local.solve(straight, hint: {57.0, 24.0, 5.0}, tmp_dir: ctx.tmp)
    assert {:ok, b} = Local.solve(turned, hint: {57.0, 24.0, 5.0}, tmp_dir: ctx.tmp)
    assert off_arcsec(center, a) < 5
    assert off_arcsec(center, b) < 5
    assert a.parity != b.parity
    turn = abs(Astro.norm180(abs(b.rotation_deg - a.rotation_deg)))
    assert_in_delta min(turn, 180 - turn), 37.0, 1.0
  end

  test "too few stars is said at once, without a minute of hopeless matching", ctx do
    # eight stars on a clean sky: nothing else for image2xy to count
    pgm = plate(@m42, keep: 8, noise: 0.5)
    t0 = System.monotonic_time(:millisecond)
    assert Local.solve(pgm, hint: {84.0, -5.0, 10.0}, tmp_dir: ctx.tmp, runner: {RecordingRunner, test_pid: self()}) == {:error, :too_few_stars}
    assert System.monotonic_time(:millisecond) - t0 < 5_000
    # the star count came from image2xy; solve-field never ran
    assert_received {:ran, "image2xy", _, {:ok, 0, out}}
    assert Local.stars(out) < 15
    refute_received {:ran, "solve-field", _, _}
  end

  if !System.find_executable("cjpeg"), do: @tag(skip: "cjpeg (libjpeg) is not here to make a JPEG")

  test "a phone's JPEG goes djpeg, an-pnmtofits, image2xy, solve-field, and never near Python", ctx do
    pgm_path = Path.join(ctx.tmp, "m42.pgm")
    jpg_path = Path.join(ctx.tmp, "m42.jpg")
    File.write!(pgm_path, plate(@m42))
    {_, 0} = System.cmd("cjpeg", ["-quality", "92", "-outfile", jpg_path, pgm_path])
    jpeg = File.read!(jpg_path)
    File.rm!(pgm_path)
    File.rm!(jpg_path)
    assert Photo.format(jpeg) == :jpeg

    # the plain path: no eyepiece to crop to, so no clean-up pass
    assert {:ok, sol} = Local.solve(jpeg, hint: {84.0, -5.0, 10.0}, tmp_dir: ctx.tmp, clean: false, runner: {RecordingRunner, test_pid: self()})
    assert off_arcsec(@m42, sol) < 5
    assert sol.stars >= 15

    ran = collect_ran([])
    assert Enum.map(ran, &elem(&1, 0)) == ["djpeg", "an-pnmtofits", "image2xy", "solve-field"]
    {"solve-field", args, {:ok, _, out}} = List.last(ran)
    assert "--no-remove-lines" in args
    # solve-field says "Running command: ..." whenever it hands off to a helper (image2pnm is Python)
    refute out =~ "Running command"
    refute out =~ ~r/python/i
  end

  if !System.find_executable("cjpeg"), do: @tag(skip: "cjpeg (libjpeg) is not here to make a JPEG")

  test "a phone photo through the whole queue: captured, stored, solved for real, fitted", ctx do
    pgm_path = Path.join(ctx.tmp, "q.pgm")
    jpg_path = Path.join(ctx.tmp, "q.jpg")
    File.write!(pgm_path, plate(@m42))
    {_, 0} = System.cmd("cjpeg", ["-quality", "92", "-outfile", jpg_path, pgm_path])
    jpeg = File.read!(jpg_path)
    id = "sim-queue-#{System.unique_integer([:positive])}"
    Controller.Plates.subscribe(id)

    cap = %{
      mount: id, at: DateTime.utc_now(), homed: true, homed_at: 1, tracking: false, moving: false,
      enc: %{ra_deg: 0.0, dec_deg: -40.0, ra_steps: nil, dec_steps: nil, ra_running: false, dec_running: false},
      hint: %{ra_deg: 84.0, dec_deg: -5.0, radius_deg: 10.0}
    }

    try do
      assert {:ok, 1} = Controller.Plates.add(id, jpeg, cap)
      view = await_solved(id)
      [plate] = view.plates
      assert plate.state == :solved, "plate #{inspect({plate.state, plate.reason})}"
      assert Astro.separation_radec(83.82, -5.39, plate.solution.ra_deg, plate.solution.dec_deg) * 3600 < 5
      assert plate.solution.solver == "this machine"
      assert File.exists?(Path.join([Controller.Plates.Store.dir(), view.session, plate.file]))
      assert view.report.n == 1
    after
      Controller.Plates.clear(id)
    end
  end

  defp await_solved(id) do
    receive do
      {:plates, ^id, %{plates: [%{state: s}]} = view} when s in [:solved, :failed] -> view
      {:plates, ^id, _} -> await_solved(id)
    after
      30_000 -> flunk("the plate never solved")
    end
  end

  defp solve_dirs(tmp), do: tmp |> File.ls!() |> Enum.filter(&String.starts_with?(&1, "observatory-solve-"))

  defp collect_ran(acc) do
    receive do
      {:ran, name, args, result} -> collect_ran(acc ++ [{name, args, result}])
    after
      0 -> acc
    end
  end

  test "a deadline kills solve-field and everything it started", ctx do
    # a solve-field that never finishes and starts a helper of its own, as the real one does
    fake = Path.join(ctx.tmp, "slow-solve-field")
    # a duration no other process on this machine is sleeping for
    nap = "3#{System.unique_integer([:positive])}.5"
    File.write!(fake, "#!/bin/sh\nsleep #{nap} &\nsleep #{nap}\n")
    File.chmod!(fake, 0o755)

    t0 = System.monotonic_time(:millisecond)
    assert Local.solve(plate(@m42), solve_field: fake, timeout: 1_500, tmp_dir: ctx.tmp) == {:error, :timeout}
    assert System.monotonic_time(:millisecond) - t0 < 3_000
    Process.sleep(200)
    # no solve-field, no helper
    assert {_, 1} = System.cmd("pgrep", ["-f", "sleep #{nap}"], stderr_to_stdout: true)
    # and nothing left on disk
    assert solve_dirs(ctx.tmp) == []
    File.rm!(fake)
  end

  test "a solve whose caller dies takes its programs with it", ctx do
    fake = Path.join(ctx.tmp, "slower-solve-field")
    nap = "2#{System.unique_integer([:positive])}.5"
    File.write!(fake, "#!/bin/sh\nsleep #{nap} &\nsleep #{nap}\n")
    File.chmod!(fake, 0o755)
    pgm = plate(@m42)

    caller = spawn(fn -> Local.solve(pgm, solve_field: fake, timeout: 60_000, tmp_dir: ctx.tmp) end)
    wait_for = fn wait -> if match?({_, 0}, System.cmd("pgrep", ["-f", "sleep #{nap}"])), do: :ok, else: (Process.sleep(50); wait.(wait)) end
    wait_for.(wait_for)
    Process.exit(caller, :kill)
    Process.sleep(400)
    assert {_, 1} = System.cmd("pgrep", ["-f", "sleep #{nap}"], stderr_to_stdout: true)
    assert solve_dirs(ctx.tmp) == []
    File.rm!(fake)
  end

  test "the front door solves here, through a supervised task", ctx do
    assert Solve.where() == :local
    assert {:ok, sol} = Solve.solve(plate(@m42), hint: %{ra_deg: 84.0, dec_deg: -5.0, radius_deg: 5}, tmp_dir: ctx.tmp)
    assert sol.solver == "this machine"
    assert off_arcsec(@m42, sol) < 5
  end
end
