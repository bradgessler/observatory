defmodule Controller.AutoAlignStillTest do
  @moduledoc """
  The one tap, with the Sony a6000 on the telescope (#111): a tripod set down
  anyhow (the polar axis 27° from the pole, as it was on 3 October), the axes
  zeroed, Align with the Camera. It points up high, takes finder pictures with
  the stills camera, has them plate solved, and the alignment they make lands
  a Go To in a low-power eyepiece and holds it there.

  The software is never told the truth. Only the stand-in plate solver reads
  it, the way a real one reads the sky.
  """
  use ExUnit.Case, async: false

  alias Controller.{AutoAlign, Plates, StillCamera}
  alias Controller.Sky.Centre
  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Lineup, Pointing, Stars, Tracker}

  @moduletag timeout: 300_000

  # a plate solver that reads the sky: where the simulated tube truly points as the picture is solved
  defmodule Sky do
    def solve(_image, _opts) do
      id = Application.get_env(:controller, :auto_align_still_mount)

      case Truth.radec(Mount.snapshot(id), DateTime.utc_now()) do
        {ra, dec} -> {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 0.66, height_deg: 0.44, rotation_deg: 0.0, parity: "neg", seconds: 0.1, stars: 30}}
        nil -> {:error, :too_few_stars}
      end
    end
  end

  setup do
    cam = "sim-still-aa-#{System.unique_integer([:positive])}"
    id = "sim-aa-still-#{System.unique_integer([:positive])}"

    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}}, id: :sim_camera)
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    # a picture from a test before may still be coming down
    Enum.find(1..300, fn _ -> not StillCamera.status().busy or (Process.sleep(50) && false) end)

    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    Lineup.clear(id)
    # 27° from the pole: 12° too low and 24° round to the west, encoders not quite zeroed
    Truth.put(id, %{axis_alt: Pointing.site().lat - 12.0, axis_az: 336.0, off_ra: 1.0, off_dec: -1.5})

    solver = Application.get_env(:controller, :solver)
    Application.put_env(:controller, :solver, backend: Sky)
    Application.put_env(:controller, :auto_align_still_mount, id)
    AutoAlign.subscribe()

    on_exit(fn ->
      if solver, do: Application.put_env(:controller, :solver, solver), else: Application.delete_env(:controller, :solver)
      Application.delete_env(:controller, :auto_align_still_mount)
      StillCamera.continuous(false)
      Tracker.stop(id)
      Lineup.clear(id)
      Plates.clear(id)
    end)

    %{id: id, ref: Enum.find(Mount.list(), &(&1.id == id))}
  end

  test "one tap from home: up high, finder pictures, and a Go To that lands in the eyepiece and stays", %{id: id, ref: ref} do
    assert AutoAlign.camera() == :still
    :ok = AutoAlign.start(id, overhead: true)

    assert_receive {:auto_align, ^id, %{done: true} = run}, 240_000
    assert run.ok, run.words
    assert run.camera == :still
    assert run.words =~ "Found it: 4 frames agree"

    # the pictures were the stills camera's finders, on this mount's plates
    assert [_, _, _, _] = Enum.filter(Plates.view(id).plates, &(&1.state == :solved and &1[:finder] == true))

    # the Start page's lock: enough points, agreeing well enough to just look
    status = Lineup.status(id)
    assert status.n == 4
    assert "just look" in status.good_for, "4 points agreeing to #{status.rms_arcmin}′"

    # what it worked out is the crooked tripod, never having been told it
    fitted = Lineup.model(id)
    truth = Truth.get(id)
    assert_in_delta fitted.axis_alt, truth.axis_alt, 1.0
    assert abs(Astro.norm180(fitted.axis_az - truth.axis_az)) < 2.0

    # a Go To somewhere else in the sky lands in a low-power eyepiece (0.6° across at 2032 mm)
    ctx = fn -> Pointing.context(DateTime.utc_now(), id) end
    here = Truth.looking_at(Mount.snapshot(id), ctx.())
    target = far_star(here, ctx.())
    assert {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), target, ctx.(), track: true)
    settle(id)
    landed = off_centre(id, target, ctx.())
    assert landed < 0.2, "a Go To after the camera's alignment should land in the eyepiece; #{target.name} was #{Float.round(landed, 3)}° off"

    # and the model's hold keeps it there on a polar axis 27° out, where the mount's own drive would
    # drift it out of a 0.6° field in a few minutes
    Process.sleep(20_000)
    assert %{name: name} = Tracker.status(id)
    assert name == target.name
    held = off_centre(id, target, ctx.())
    assert abs(held - landed) * 60 < 0.5, "held #{Float.round(held * 60, 2)}′ off after 20 s (landed #{Float.round(landed * 60, 2)}′)"
  end

  test "Go To and Centre: the picture says how far off it landed, a nudge puts it in the middle, the hold keeps it", %{id: id} do
    :ok = AutoAlign.start(id, overhead: true)
    assert_receive {:auto_align, ^id, %{done: true, ok: true}}, 240_000

    # the tube shifts against the encoders after the alignment (an SCT's mirror, a clutch): Go To now
    # lands about 20 arcminutes off, outside a 25 mm eyepiece's field at 2032 mm
    t = Truth.get(id)
    Truth.put(id, %{t | off_ra: t.off_ra + 0.3, off_dec: t.off_dec - 0.2})
    ctx = fn -> Pointing.context(DateTime.utc_now(), id) end
    target = far_star(Truth.looking_at(Mount.snapshot(id), ctx.()), ctx.())

    Centre.subscribe()
    :ok = Centre.start(id, target)
    assert_receive {:centre, ^id, %{done: true} = run}, 150_000
    assert run.ok, run.words
    assert run.tries >= 2, "it should have had to nudge: #{run.words}"
    assert run.words =~ "centred"
    centred = off_centre(id, target, ctx.()) * 60
    assert centred < 2.0, "#{target.name} is #{Float.round(centred, 2)}′ from the middle"

    # and the model's hold keeps the centred place, not the model's own idea of the target
    Process.sleep(10_000)
    assert %{name: name} = Tracker.status(id)
    assert name == target.name
    held = off_centre(id, target, ctx.()) * 60
    assert held < 2.5, "held #{Float.round(held, 2)}′ off after 10 s (centred at #{Float.round(centred, 2)}′)"
  end

  test "Go To and Centre with no camera says so and moves nothing", %{id: id} do
    Process.sleep(200)
    stop_supervised!(:sim_camera)
    Enum.find(1..80, fn _ -> StillCamera.status().camera == nil or (Process.sleep(100) && false) end)
    star = Enum.find(Stars.all(), &(&1.name == "Vega"))
    assert Centre.start(id, star) == {:error, :no_camera}
    refute Mount.snapshot(id).axes.ra.goto_pending
  end

  test "with no camera on the telescope it says so and moves nothing", %{id: id} do
    assert AutoAlign.start(id, camera: nil) == {:error, :no_camera}
    refute Mount.snapshot(id).axes.ra.goto_pending
  end

  # a named star well up and at least 30° from where the tube is: a real Go To
  defp far_star(here, ctx) do
    lst = Astro.lst_deg(ctx.now, ctx.site.lon)

    Stars.all()
    |> Enum.filter(fn s ->
      {alt, _az} = Astro.alt_az(s.ra_deg, s.dec_deg, ctx.site.lat, lst)
      sep = Astro.separation_radec(here.ra_deg, here.dec_deg, s.ra_deg, s.dec_deg)
      alt > 35 and sep > 30 and sep < 60
    end)
    |> Enum.min_by(fn s -> Astro.separation_radec(here.ra_deg, here.dec_deg, s.ra_deg, s.dec_deg) end)
  end

  # how far the tube really is from an object, in degrees: what the eyepiece shows
  defp off_centre(id, obj, ctx) do
    %{ra_deg: ra, dec_deg: dec} = Truth.looking_at(Mount.snapshot(id), ctx)
    Astro.separation_radec(ra, dec, obj.ra_deg, obj.dec_deg)
  end

  defp settle(id, tries \\ 400) do
    s = Mount.snapshot(id)

    if (s.axes.ra.goto_pending or s.axes.dec.goto_pending) and tries > 0 do
      Process.sleep(250)
      settle(id, tries - 1)
    end

    # the tracker's first ticks after the landing
    Process.sleep(2_000)
  end
end
