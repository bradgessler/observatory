defmodule Controller.AutoAlignStillTest do
  @moduledoc """
  The one tap, with the Sony a6000 on the telescope (#111): a tripod set down
  anyhow (the polar axis 27° from the pole, as it was on 3 October), the axes
  zeroed, Align with the Camera. It points up high, takes finder pictures with
  the stills camera, has them plate solved, and the alignment they make lands
  a Go To in a low-power eyepiece and holds it there.

  The software is never told the truth. Only the stand-in plate solver reads
  it, the way a real one reads the sky.

  And with no home at all (8 October): the same tap from wherever the
  telescope points. No picture can say which side the counterweight is on,
  so the run's last words ask, and Go To waits for the answer (#113).
  """
  use ExUnit.Case, async: false

  alias Controller.{AutoAlign, Plates, StillCamera}
  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars, Tracker}

  @moduletag timeout: 300_000

  # a plate solver that reads the sky: where the simulated tube truly points as the picture is solved
  defmodule Sky do
    def solve(_image, _opts) do
      id = Application.get_env(:controller, :auto_align_still_mount)

      case true_radec(Mount.snapshot(id), DateTime.utc_now()) do
        {ra, dec} -> {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 0.66, height_deg: 0.44, rotation_deg: 0.0, parity: "neg", seconds: 0.1, stars: 30}}
        nil -> {:error, :too_few_stars}
      end
    end

    # Zeroed, the truth counts from home. Never zeroed, the counts run from wherever the mount woke,
    # and the truth's offsets say where that was: the sky is there all the same.
    def true_radec(%{homed: true} = snap, now), do: Truth.radec(snap, now)

    def true_radec(%{id: id, axes: %{ra: ra, dec: dec}}, now) do
      site = Pointing.site()
      Model.radec(Truth.get(id), Pointing.pointing(), ra.degrees, dec.degrees, site.lat, Astro.lst_deg(now, site.lon))
    end
  end

  setup tags do
    cam = "sim-still-aa-#{System.unique_integer([:positive])}"
    id = "sim-aa-still-#{System.unique_integer([:positive])}"

    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}})
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    # a picture from a test before may still be coming down
    Enum.find(1..300, fn _ -> not StillCamera.status().busy or (Process.sleep(50) && false) end)

    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Lineup.clear(id)

    if tags[:no_home] do
      # the same crooked tripod, never zeroed: it woke 60° east of the meridian with the tube 50° off
      # the polar axis, up in the sky, its counterweight well below level (KnownMount's convention)
      pointing = Controller.Settings.get("pointing")
      Controller.Settings.put("pointing", %{"ha_sign" => 1, "dec_sign" => -1})
      on_exit(fn -> Controller.Settings.put("pointing", pointing) end)
      Truth.put(id, %{axis_alt: Pointing.site().lat - 12.0, axis_az: 336.0, off_ra: -60.0, off_dec: 50.0})
    else
      :ok = Mount.set_home(id)
      # 27° from the pole: 12° too low and 24° round to the west, encoders not quite zeroed
      Truth.put(id, %{axis_alt: Pointing.site().lat - 12.0, axis_az: 336.0, off_ra: 1.0, off_dec: -1.5})
    end

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

  test "with no camera on the telescope it says so and moves nothing", %{id: id} do
    assert AutoAlign.start(id, camera: nil) == {:error, :no_camera}
    refute Mount.snapshot(id).axes.ra.goto_pending
  end

  @tag :no_home
  test "one tap with no home: the pictures align it, the last words ask the counterweight's side, and Go To waits for it", %{id: id, ref: ref} do
    refute Mount.snapshot(id).homed
    :ok = AutoAlign.start(id)

    assert_receive {:auto_align, ^id, %{done: true} = run}, 240_000
    assert run.ok, run.words
    assert run.words =~ "Aligned: 4 frames agree"
    assert run.words =~ "Is the counterweight bar below or above level right now?"
    status = Lineup.status(id)
    assert status.n == 4 and "just look" in status.good_for
    assert status.counterweight == :guessed

    # a Go To now moves nothing
    ctx = fn -> Pointing.context(DateTime.utc_now(), id) end
    here = Sky.true_radec(Mount.snapshot(id), DateTime.utc_now())
    target = east_star(here, ctx.())
    snap = Mount.snapshot(id)
    assert Pointing.slew(ref, snap, target, ctx.(), track: true) == {:error, :counterweight_unknown}
    # (the mount's own sidereal drive, which the run turned on to keep the stars still, runs on)
    now = Mount.snapshot(id)
    refute Enum.any?(now.axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) or ax.mode == :goto and ax.running end)
    refute now.axes.dec.running
    assert_in_delta now.axes.dec.degrees, snap.axes.dec.degrees, 1.0e-6
    refute Tracker.active?(id)

    # told by someone looking at it (below level, 45° to 75° east of the meridian): Go To goes, and
    # lands in a low-power eyepiece on a polar axis 27° out with no home
    assert {:ok, _} = Lineup.set_counterweight(id, Mount.snapshot(id), :below)
    assert {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), target, ctx.(), track: true)
    settle(id)
    {ra, dec} = Sky.true_radec(Mount.snapshot(id), DateTime.utc_now())
    landed = Astro.separation_radec(ra, dec, target.ra_deg, target.dec_deg)
    assert landed < 0.2, "#{target.name} was #{Float.round(landed, 3)}° off"
    assert %{name: name} = Tracker.status(id)
    assert name == target.name
  end

  # a named star well up, east of the meridian and 15° to 50° from where the tube is: a Go To
  # that stays on this side of the pier
  defp east_star({ra0, dec0}, ctx) do
    lst = Astro.lst_deg(ctx.now, ctx.site.lon)

    Stars.all()
    |> Enum.filter(fn s ->
      {alt, _az} = Astro.alt_az(s.ra_deg, s.dec_deg, ctx.site.lat, lst)
      ha = Astro.hour_angle(lst, s.ra_deg)
      sep = Astro.separation_radec(ra0, dec0, s.ra_deg, s.dec_deg)
      alt > 30 and ha < -10 and ha > -80 and sep > 15 and sep < 50
    end)
    |> Enum.min_by(fn s -> Astro.separation_radec(ra0, dec0, s.ra_deg, s.dec_deg) end, fn -> flunk("no bright star east of the meridian near the tube") end)
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
