defmodule Controller.Sky.SolveLocalTest do
  @moduledoc """
  The plate solver without the sky: how it reads solve-field's real output,
  what it asks for, and what the front door does with a stub or a crash.
  Real solves of synthetic plates are in `solve_plates_test.exs`.
  """
  use ExUnit.Case, async: false

  alias Controller.Sky.Solve
  alias Controller.Sky.Solve.Local

  # captured from `solve-field` 0.97 on a 1° plate around M42
  @solved """
  Reading input file 1 of 1: "m42.jpg"...
  Running command: /opt/homebrew/bin/image2pnm --infile m42.jpg --uncompressed-outfile /tmp/tmp.uncompressed.xkYGrH --outfile /tmp/tmp.ppm.2gBZ9C --ppm --mydir /opt/homebrew/bin/solve-field
  jpegtopnm: WRITING PPM FILE
  Read file stdin: 1200 x 1200 pixels x 1 color(s); maxval 255
  Using 8-bit output
  Extracting sources...
  simplexy: found 5938 sources.
  Solving...
  Reading file "./m42.axy"...
  Only searching for solutions within 10 degrees of RA,Dec (86,-2)
    log-odds ratio 121.416 (5.3741e+52), 20 match, 0 conflict, 51 distractors, 28 index.
    RA,Dec = (83.8214,-5.39111), pixel scale 3.00588 arcsec/pix.
    Hit/miss:   Hit/miss: -++-++---+-+++---+----+---+--++--+----+---+-------++---------+--------+(best)-----------------------------
  Field 1: solved with index index-4109.fits.
  Field 1 solved: writing to file ./m42.solved to indicate this.
  Field: m42.jpg
  Field center: (RA,Dec) = (83.819891, -5.390058) deg.
  Field center: (RA H:M:S, Dec D:M:S) = (05:35:16.774, -05:23:24.208).
  Field size: 59.9961 x 59.9985 arcminutes
  Field rotation angle: up is -142.982 degrees E of N
  Field parity: neg
  Creating new FITS file "./m42.new"...
  """

  @unsolved """
  Reading input file 1 of 1: "dark.pgm"...
  Extracting sources...
  simplexy: found 3 sources.
  Solving...
  Reading file "./dark.axy"...
  Field 1 did not solve (index index-4114.fits, field objects 1-3).
  Field 1 did not solve (index index-4107.fits, field objects 1-3).
  Did not solve (or no WCS file was written).
  """

  describe "reading solve-field" do
    test "a solved field: centre, size, rotation, parity, scale, stars, index" do
      assert {:ok, sol} = Local.parse(@solved)
      assert sol.ra_deg == 83.819891
      assert sol.dec_deg == -5.390058
      assert_in_delta sol.width_deg, 59.9961 / 60, 1.0e-9
      assert_in_delta sol.height_deg, 59.9985 / 60, 1.0e-9
      assert sol.rotation_deg == -142.982
      assert sol.parity == "neg"
      assert sol.pixscale_arcsec == 3.00588
      assert sol.index == "index-4109"
      assert Local.stars(@solved) == 5938
    end

    test "sizes in degrees and arcseconds read the same" do
      deg = String.replace(@solved, "59.9961 x 59.9985 arcminutes", "1.2 x 0.9 degrees")
      assert {:ok, %{width_deg: 1.2, height_deg: 0.9}} = Local.parse(deg)
      sec = String.replace(@solved, "59.9961 x 59.9985 arcminutes", "360 x 270 arcseconds")
      assert {:ok, %{width_deg: w}} = Local.parse(sec)
      assert_in_delta w, 0.1, 1.0e-9
    end

    test "no field centre is no solution, whatever else it said" do
      assert Local.parse(@unsolved) == {:error, :no_solution}
      assert Local.parse("") == {:error, :no_solution}
    end

    test "solve-field is asked to match a star list, with nothing that needs Python" do
      args = Local.args("/t/photo.xy.fits", {4032, 3024}, "/t", hint: %{ra_deg: 86.0, dec_deg: -2.0, radius_deg: 10.0}, scale: {0.5, 2.0}, index_config: "/c.cfg", cpu_ms: 30_000)
      assert ["--config", "/c.cfg" | _] = args
      assert List.last(args) == "/t/photo.xy.fits"
      joined = Enum.join(args, " ")
      # the two clean-up passes are Python scripts: both off
      assert joined =~ "--no-remove-lines --uniformize 0"
      assert joined =~ "--width 4032 --height 3024 --x-column X --y-column Y --sort-column FLUX"
      assert joined =~ "--ra 86.000000 --dec -2.000000 --radius 10.000000"
      assert joined =~ "--scale-low 0.500000 --scale-high 2.000000"
      assert joined =~ "--cpulimit 30"
      refute Local.args("/t/p.xy.fits", {800, 600}, "/t", index_config: "/c") |> Enum.member?("--ra")
    end

    test "the eyepiece is the biggest bright region, not the glare beside it" do
      # magick's listing for plate fifteen of the first night: the disc (4), a
      # flare of moonlight at the frame's edge (2), and a speck (1)
      listing = """
      Objects (id: bounding-box centroid area mean-color):
        0: 2576x1932+0+0 1304.2,921.4 3.81061e+06 gray(0)
        4: 1212x1201+594+535 1201.7,1137.5 1.13597e+06 gray(255)
        2: 340x132+2236+0 2401.9,70.2 24918 gray(255)
        3: 107x52+2398+0 2451.0,21.5 4324 gray(0)
        1: 52x36+2168+0 2193.4,12.3 1006 gray(255)
      """

      assert Local.eyepiece_disc(listing) == %{id: "4", box: "1212x1201+594+535"}

      # nothing bright: no eyepiece
      assert Local.eyepiece_disc("Objects (id: bounding-box centroid area mean-color):\n  0: 10x10+0+0 5.0,5.0 100 gray(0)\n") == nil

      # a star field straight off a camera: the halo of one bright star is not an eyepiece
      halo = """
      Objects (id: bounding-box centroid area mean-color):
        0: 1200x1200+0+0 600.0,600.0 1.43e+06 gray(0)
        1: 110x110+300+300 355.0,355.0 9500 gray(255)
      """

      assert Local.eyepiece_disc(halo) == nil
    end

    test "a 12 MP phone photo is downsampled by 2, a huge one by 4" do
      assert Local.downsample(:auto, {4032, 3024}) == 2
      assert Local.downsample(:auto, {8064, 6048}) == 4
      assert Local.downsample(:auto, {800, 600}) == 1
      assert Local.downsample(3, {800, 600}) == 3
    end

    test "programs and the index config come from options, then config, then the machine" do
      Application.put_env(:controller, :solver, index_config: "/from/config.cfg", djpeg: "/nowhere/djpeg")

      try do
        assert Local.index_config() == "/from/config.cfg"
        assert Local.index_config(index_config: "/from/opts.cfg") == "/from/opts.cfg"
        # a configured path that is not there is not quietly replaced by another
        assert Local.executable(:djpeg) == nil
        refute Local.available?()
      after
        Application.delete_env(:controller, :solver)
      end
    end

    test "no solver is a plain answer, not a crash" do
      assert Local.solve("P5\n1 1\n255\n" <> <<0>>, solve_field: "/nowhere/solve-field") == {:error, :no_solver}
      assert Local.solve("P5\n1 1\n255\n" <> <<0>>, index_config: "/nowhere/astrometry.cfg") == {:error, :no_solver}
      refute Local.available?(solve_field: "/nowhere/solve-field")
    end

    @tag capture_log: true
    test "a front door with a stubbed solver tags where it solved, and contains a crash" do
      defmodule Crasher do
        def solve(_image, _opts), do: raise("boom")
      end

      defmodule Answer do
        def solve(_image, _opts), do: {:ok, %{ra_deg: 1.0, dec_deg: 2.0}}
      end

      assert {:ok, %{ra_deg: 1.0, solver: solver}} = Solve.solve("P5 1 1 255 x", backend: Answer)
      assert solver =~ "Answer"
      assert {:error, {:crashed, _}} = Solve.solve("P5 1 1 255 x", backend: Crasher)
      assert Solve.where(backend: Answer) == {:module, Answer}
    end
  end
end
