defmodule Controller.ScopeCameraTest do
  @moduledoc """
  The telescope camera: its frames measured (stars, focus), shown (a PNG a
  phone can display), its controls read from v4l2-ctl, and the whole
  find-where-it's-pointing loop run on a simulated mount with a simulated
  camera, so tomorrow night only the camera is new.
  """
  use ExUnit.Case, async: false

  alias Controller.{AutoAlign, Plates, ScopeCamera}
  alias Controller.ScopeCamera.{Device, Image, Sim}
  alias Controller.Sky.Lineup

  # a frame with stars of a given blur at known places
  defp frame(sigma, stars \\ [{100, 80, 200}, {300, 150, 150}, {500, 60, 120}]) do
    {w, h} = {640, 240}

    light =
      for {sx, sy, b} <- stars, y <- (sy - 12)..(sy + 12), x <- (sx - 12)..(sx + 12), reduce: %{} do
        acc -> Map.update(acc, y * w + x, 0, & &1) |> Map.update!(y * w + x, &(&1 + b * :math.exp(-((x - sx) ** 2 + (y - sy) ** 2) / (2 * sigma * sigma))))
      end

    px = for i <- 0..(w * h - 1), into: <<>>, do: <<min(round(20 + rem(i * 7919, 5) + Map.get(light, i, 0.0)), 255)>>
    %{w: w, h: h, px: px}
  end

  describe "a frame" do
    test "finds the stars, brightest first, where they are" do
      stars = Image.stars(frame(1.5))
      assert length(stars) == 3
      [first | _] = stars
      assert_in_delta first.x, 100, 0.5
      assert_in_delta first.y, 80, 0.5
    end

    test "a sharper star has a smaller half-flux radius: the focus number" do
      sharp = frame(1.2) |> Image.stars() |> Image.focus()
      soft = frame(3.0) |> Image.stars() |> Image.focus()
      assert sharp.stars == 3
      assert sharp.hfr < soft.hfr
    end

    test "a camera that lifts its own corners (the SV105C, cap on): the corners aren't stars, the stars still are" do
      {w, h} = {480, 270}
      # black at 17, flat as the camera's own smoothing leaves it, corners up to 6 levels higher
      lift = fn x, y -> round(6 * min(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2, 1.0) ** 2) end
      stars = [{100, 80, 120}, {300, 150, 90}, {400, 60, 60}, {60, 200, 80}]

      px =
        for y <- 0..(h - 1), x <- 0..(w - 1), into: <<>> do
          light = Enum.reduce(stars, 0, fn {sx, sy, b}, acc -> acc + b * :math.exp(-((x - sx) ** 2 + (y - sy) ** 2) / 4.5) end)
          <<min(round(17 + lift.(x, y) + light), 255)>>
        end

      img = %{w: w, h: h, px: px}
      found = Image.stars(img)
      assert length(found) == 4
      assert Image.verdict(Image.stats(img), found, min: 4) == :stars

      # and cap on, no stars: nothing at all, not a corner full of "stars"
      dark = %{img | px: for(y <- 0..(h - 1), x <- 0..(w - 1), into: <<>>, do: <<17 + lift.(x, y)>>)}
      assert Image.stars(dark) == []
    end

    test "hot pixels, alone or in pairs, aren't stars" do
      {w, h} = {200, 100}
      hot = %{30 * w + 40 => 120, 30 * w + 41 => 110, 70 * w + 150 => 200}
      img = %{w: w, h: h, px: for(i <- 0..(w * h - 1), into: <<>>, do: <<Map.get(hot, i, 17 + rem(i * 7919, 3))>>)}
      assert Image.stars(img) == []
    end

    test "what's turned away is said, with why: the border, specks too small, specks too sharp" do
      {w, h} = {640, 240}
      # a hot pair mid-frame, a speck in the corner, a real star
      extra = %{(100 * w + 300) => 140, (100 * w + 301) => 130, (3 * w + 4) => 120}
      base = frame(1.5, [{500, 150, 180}])
      px = for i <- 0..(w * h - 1), into: <<>>, do: <<max(:binary.at(base.px, i), Map.get(extra, i, 0))>>
      found = Image.find(%{base | px: px})
      assert [%{x: x}] = found.stars
      assert_in_delta x, 500, 1
      whys = Enum.map(found.rejected, & &1.why)
      assert :border in whys
      assert Enum.any?(whys, &(&1 in [:small, :sharp]))
      assert found.border == 16
    end

    test "detail: near nothing for noise, more for sharp stars than soft ones" do
      blank = frame(1.5, [])
      noise = Image.detail(blank, Image.stats(blank))
      # out of focus the same light spreads wider, so it's dimmer: peak falls as the square of the width
      dim = fn sigma -> for {x, y, b} <- [{100, 80, 200}, {300, 150, 150}, {500, 60, 120}], do: {x, y, b * 1.2 * 1.2 / (sigma * sigma)} end
      sharp = frame(1.2, dim.(1.2))
      soft = frame(3.0, dim.(3.0))
      assert noise < 1.0
      assert Image.detail(sharp, Image.stats(sharp)) > Image.detail(soft, Image.stats(soft))
      assert Image.detail(soft, Image.stats(soft)) > noise
    end

    test "a sky with nothing in it has no stars, and says so" do
      blank = %{w: 100, h: 100, px: :binary.copy(<<20>>, 10_000)}
      assert Image.stars(blank) == []
      assert Image.focus([]) == %{hfr: nil, stars: 0}
    end

    test "a phone can show it: a PNG, the sky dark and the stars bright" do
      img = frame(1.5)
      png = img |> Image.stretch() |> Image.png()
      assert <<137, 80, 78, 71, 13, 10, 26, 10, _::binary>> = png
      shown = Image.stretch(img)
      assert :binary.at(shown.px, 80 * 640 + 100) > 200
      assert :binary.at(shown.px, 200 * 640 + 20) < 60
    end

    test "a bright, even picture shows bright, not black: the background is never drawn darker than it is" do
      # the sensor under the garage lights, no lens: 204 everywhere
      lit = %{w: 160, h: 90, px: :binary.copy(<<204>>, 160 * 90)}
      assert :binary.at(Image.stretch(lit).px, 45 * 160 + 80) == 204

      # a dark sky is lifted to a dim grey, so its grain shows; a star still goes white
      lut = Image.curve(%{background: 20, noise: 2.0})
      assert elem(lut, 20) in 20..40
      assert elem(lut, 120) == 255
    end

    test "averaging frames keeps the picture and the size" do
      a = %{w: 2, h: 1, px: <<10, 200>>}
      b = %{w: 2, h: 1, px: <<30, 100>>}
      assert Image.average([a, b]) == %{w: 2, h: 1, px: <<20, 150>>}
    end

    test "PGM in and out" do
      img = frame(1.5)
      assert {:ok, ^img} = img |> Image.pgm() |> Image.from_pgm()
      assert {:ok, %{w: 2, h: 1}} = Image.from_pgm("P5\n# a comment\n2 1\n255\n" <> <<1, 2>>)
    end
  end

  describe "the camera's controls" do
    # what v4l2-ctl says about a typical UVC planetary camera
    @ctrls """
    User Controls

                         brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0
                               gain 0x00980913 (int)    : min=0 max=100 step=1 default=32 value=32
    Camera Controls

                      auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
             exposure_time_absolute 0x009a0902 (int)    : min=1 max=5000 step=1 default=157 value=157 flags=inactive
    """

    test "are read from v4l2-ctl, with their ranges" do
      c = Device.parse_controls(@ctrls)
      assert c["gain"].max == 100
      assert c["exposure_time_absolute"].max == 5000
      assert c["exposure_time_absolute"].inactive
      assert c["auto_exposure"].value == 3
    end
  end

  describe "the camera's sizes and formats" do
    # what v4l2-ctl says about a cheap 1080p UVC camera: JPEG fast, raw slow
    @formats """
    ioctl: VIDIOC_ENUM_FMT
    \tType: Video Capture

    \t[0]: 'MJPG' (Motion-JPEG, compressed)
    \t\tSize: Discrete 1920x1080
    \t\t\tInterval: Discrete 0.033s (30.000 fps)
    \t\tSize: Discrete 1280x720
    \t\t\tInterval: Discrete 0.033s (30.000 fps)
    \t[1]: 'YUYV' (YUYV 4:2:2)
    \t\tSize: Discrete 1920x1080
    \t\t\tInterval: Discrete 0.200s (5.000 fps)
    \t\tSize: Discrete 640x480
    \t\t\tInterval: Discrete 0.033s (30.000 fps)
    \t[2]: 'H264' (H.264, compressed)
    \t\tSize: Discrete 1920x1080
    """

    test "are read from v4l2-ctl, in ffmpeg's names, with their slowest frame rate, skipping ones it can't turn into a picture" do
      modes = Device.parse_modes(@formats)
      assert %{format: "mjpeg", size: {1920, 1080}, fps: 30.303} in modes
      assert %{format: "yuyv422", size: {640, 480}, fps: 30.303} in modes
      refute Enum.any?(modes, &(&1.format == nil))
      assert [%{fps: 1.0}] = Device.parse_modes("\t[0]: 'YUYV' (YUYV)\n\t\tSize: Discrete 1920x1080\n\t\t\tInterval: Stepwise 0.033s - 1.000s with step 0.001s\n")
    end

    test "pictures are taken at the full size, raw rather than JPEG" do
      assert Device.best_mode(Device.parse_modes(@formats)) == %{format: "yuyv422", size: {1920, 1080}, fps: 5.0}
      assert Device.best_mode(Device.parse_modes("\t[0]: 'MJPG' (Motion-JPEG)\n\t\tSize: Discrete 1920x1080\n\t[1]: 'YUYV' (YUYV)\n\t\tSize: Discrete 640x480\n")) == %{format: "mjpeg", size: {1920, 1080}}
      assert Device.best_mode([]) == nil
    end

    test "softer stars are shrunk more before solving, so a ring reads as one star" do
      assert AutoAlign.downsample(1.6) == 1
      assert AutoAlign.downsample(3.0) == 2
      assert AutoAlign.downsample(9.0) == 4
      assert AutoAlign.downsample(nil) == 1
    end

  end

  describe "finding where it points, on a simulated mount" do
    # a plate solver that reads the pointing a simulated frame says it was taken at
    defmodule Stub do
      def solve(image, _opts) do
        case Sim.said(image) do
          {ra, dec} -> {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 0.3, height_deg: 0.17, rotation_deg: 0.0, parity: "neg", seconds: 0.1, stars: 25}}
          nil -> {:error, :too_few_stars}
        end
      end
    end

    setup do
      id = "sim-aa-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(id)
      assert_receive {:mount, %{connected: true}}, 2_000

      solver = Application.get_env(:controller, :solver)
      Application.put_env(:controller, :solver, backend: Stub)
      ScopeCamera.simulate(true)
      AutoAlign.subscribe()

      on_exit(fn ->
        if solver, do: Application.put_env(:controller, :solver, solver), else: Application.delete_env(:controller, :solver)
        ScopeCamera.simulate(false)
        Lineup.clear(id)
        Plates.clear(id)
      end)

      %{id: id}
    end

    @tag timeout: 120_000
    test "pictures, moves, and four pictures that agree become the alignment", %{id: id} do
      assert Sim.pointing(id, DateTime.utc_now())
      :ok = AutoAlign.start(id, plan: [{0, 0}, {10, 0}, {10, 8}, {0, 8}], settle_ms: 800)

      assert_receive {:auto_align, ^id, %{done: true, ok: true, words: words}}, 90_000
      assert words =~ "Found it: 4 frames agree"

      st = Lineup.status(id)
      assert st.n == 4
      assert st.rms_arcmin < 3.0
      refute Lineup.stale?(id)
    end

    @tag timeout: 180_000
    test "pictures of a garage or a cloud aren't solved; after three it hands the mount over, then carries on", %{id: id} do
      # nothing that reads as a star: the garage door, a cloud, a camera hopelessly out of focus
      Controller.Settings.put("sim_defocus", 3.0)
      :ok = AutoAlign.start(id, plan: [{0, 0}, {6, 0}, {6, 5}, {0, 5}], settle_ms: 800)

      assert_receive {:auto_align, ^id, %{phase: :waiting, done: false, words: words}}, 60_000
      # spread that thin, nothing reads as a star
      assert words =~ ~r/No stars/
      assert words =~ "Move the telescope to open sky"
      assert Plates.view(id).plates == []

      # the person points it at open sky and taps Continue
      Controller.Settings.put("sim_defocus", 0.0)
      :ok = AutoAlign.continue(id)
      assert_receive {:auto_align, ^id, %{done: true, ok: true}}, 90_000
      assert Lineup.status(id).n == 4
    after
      Controller.Settings.put("sim_defocus", 0.0)
    end

    @tag timeout: 120_000
    test "with no stand-in solver, a simulated camera's pictures solve themselves (the Mac, no sky)", %{id: id} do
      Application.delete_env(:controller, :solver)
      :ok = AutoAlign.start(id, plan: [{0, 0}, {8, 0}, {8, 6}, {0, 6}], settle_ms: 800)
      assert_receive {:auto_align, ^id, %{done: true, ok: true}}, 90_000
      assert [%{solution: %{solver: "simulator"}} | _] = Plates.view(id).plates
    end

    @tag timeout: 60_000
    test "STOP ends it where it is", %{id: id} do
      :ok = AutoAlign.start(id, plan: [{0, 0}, {10, 0}, {10, 8}, {0, 8}], settle_ms: 1_500)
      :ok = Mount.stop(id)
      assert_receive {:auto_align, ^id, %{done: true, ok: false, words: "Stopped" <> _}}, 20_000
    end
  end
end
