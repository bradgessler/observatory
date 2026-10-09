defmodule Controller.AlignPhotoLiveTest do
  @moduledoc """
  Align by Photo against a simulated mount set down badly on purpose, with
  the plate solver stood in for: the "photo" the page uploads carries where
  the simulated tube truly points (the sky of date, as the J2000 centre a
  solver would report). The page must read the encoders the moment the
  photo is chosen, queue it, say which bolt to turn as plates land, and make
  GoTo land once the alignment is used.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Plates
  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Lineup, Model, Pointing}
  alias Mount.Protocol, as: P

  defmodule Stub do
    @moduledoc false
    # waits while the test holds the gate shut, then answers from the "photo"
    def solve(image, _opts) do
      wait()

      case image do
        "P5 STUB " <> rest ->
          [ra, dec] = rest |> String.split() |> Enum.map(&String.to_float/1)
          {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 1.0, height_deg: 0.75, rotation_deg: 0.0, parity: "neg", seconds: 0.2, stars: 40}}

        "P5 DARK" <> _ ->
          {:error, :too_few_stars}
      end
    end

    defp wait, do: if(:persistent_term.get({__MODULE__, :open}, true), do: :ok, else: Process.sleep(10) && wait())
    def open(open?), do: :persistent_term.put({__MODULE__, :open}, open?)
  end

  setup do
    id = "sim-photo-page-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Stub.open(true)
    Application.put_env(:controller, :solver, backend: Stub)

    # 0.5° low and 0.8° east of the pole of date
    truth = %{axis_alt: Pointing.site().lat - 0.5, axis_az: 0.8, off_ra: 1.0, off_dec: -1.5}
    Truth.put(id, truth)

    on_exit(fn ->
      Stub.open(true)
      Application.delete_env(:controller, :solver)
      Plates.set_workers(Plates.default_workers())
      Plates.clear(id)
      Lineup.clear(id)
    end)

    %{id: id, truth: truth}
  end

  # Turn the simulated encoders to these angles at once (clutches loose, a
  # hand on the tube) and wait until the driver reports them, still.
  defp put_encoders(id, ra, dec) do
    for {axis, deg} <- [{"1", ra}, {"2", dec}] do
      Mount.raw(id, ":E#{axis}#{P.from_int(P.center() + P.degrees_to_steps(deg, 9_216_000))}\r")
    end

    wait_still(id, ra, dec)
  end

  defp wait_still(id, ra, dec) do
    receive do
      {:mount, %{id: ^id, axes: %{ra: %{degrees: r, deg_per_s: vr}, dec: %{degrees: d, deg_per_s: vd}}} = snap}
      when abs(r - ra) < 0.001 and abs(d - dec) < 0.001 and vr == 0 and vd == 0 ->
        snap

      {:mount, _} ->
        wait_still(id, ra, dec)
    after
      3_000 -> flunk("the encoders never settled at #{ra}, #{dec}")
    end
  end

  # what a plate solver would say about a photo at this snapshot, right now
  defp photo_of(truth, snap) do
    now = DateTime.utc_now()
    site = Pointing.site()
    {alt, az} = Model.altaz(truth, Pointing.pointing(), snap.axes.ra.degrees, snap.axes.dec.degrees)
    {ra, dec} = Astro.radec_from_altaz(alt, az, site.lat, Astro.lst_deg(now, site.lon))
    {ra, dec} = Astro.precess_to_j2000(ra, dec, now)
    # 100 bytes, so an upload can stop at any whole percent (an odd length
    # can't be split in half, and the test uploads half, then the rest)
    String.pad_trailing("P5 STUB #{:erlang.float_to_binary(ra, decimals: 8)} #{:erlang.float_to_binary(dec, decimals: 8)}", 100)
  end

  defp upload(view, name, content) do
    view
    |> file_input("#photo-form", :photo, [%{name: name, content: content, type: "image/jpeg"}])
    |> render_upload(name)
  end

  defp eventually(view, pattern, tries \\ 60) do
    html = render(view)

    cond do
      html =~ pattern -> html
      tries == 0 -> flunk("never saw #{inspect(pattern)} in:\n#{html}")
      true -> Process.sleep(50) && eventually(view, pattern, tries - 1)
    end
  end

  test "home is a shortcut, not a need: the one big key is the camera either way", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/align/photo/#{id}")
    assert html =~ "Home not set, which is fine"
    assert html =~ "Take Photo"

    :ok = Mount.set_home(id)
    Process.sleep(300)
    html = render(view)
    refute html =~ "Home not set"
    assert html =~ "Take Photo"
    assert html =~ ~s(capture="environment")
    assert html =~ ~s(accept="image/*")
    assert html =~ "Hold the telescope still until you tap Use Photo"
    assert html =~ "Point at any stars"
    assert render_async(view) =~ "Solving on"
  end

  test "photos land one by one, the polar axis says which bolt, and Use This Alignment makes GoTo land", %{conn: conn, id: id, truth: truth} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/align/photo/#{id}")

    snap = put_encoders(id, -40.0, -30.0)
    upload(view, "p1.jpg", photo_of(truth, snap))
    html = eventually(view, "Swing the RA axis")
    assert html =~ ~r/Photo 1.*RA \d{1,2}h\d\dm, Dec -?\d+°\d\d′, 60′ field/s

    # the page follows the encoders: how far RA has swung since photo 1
    put_encoders(id, 25.0, -40.0)
    assert eventually(view, "RA is 65° from photo 1: take the next one")

    snap = put_encoders(id, 25.0, -40.0)
    upload(view, "p2.jpg", photo_of(truth, snap))
    html = eventually(view, "Polar Axis")
    assert html =~ "Raise 0.5°"
    assert html =~ "Turn 0.8° west"
    assert html =~ "2 photos fit exactly"
    assert html =~ ~s(class="polar-plot")

    snap = put_encoders(id, -10.0, -50.0)
    upload(view, "p3.jpg", photo_of(truth, snap))
    html = eventually(view, "3 photos agree to")
    assert html =~ "off by"

    render_click(view, "use")
    assert eventually(view, "In Use ✓") =~ "Go To now goes through these photos"
    assert Lineup.status(id).n == 3

    # a GoTo through the photos' model lands where the object truly is
    now = DateTime.utc_now()
    ctx = Pointing.context(now, id)
    assert Pointing.lined_up?(ctx)
    site = Pointing.site()
    vega = Enum.find(Controller.Sky.Stars.all(), &(&1.name == "Vega"))
    {r, d} = Pointing.axes_for(vega, ctx)
    {alt, az} = Model.altaz(truth, Pointing.pointing(), r, d)
    {vra, vdec} = Astro.precess_from_j2000(vega.ra_deg, vega.dec_deg, now)
    {valt, vaz} = Astro.alt_az(vra, vdec, site.lat, Astro.lst_deg(now, site.lon))
    miss = Astro.separation(Astro.altaz_vec(alt, az), Astro.altaz_vec(valt, vaz)) * 60
    assert miss < 3, "missed Vega by #{miss}′"

    # Start Over forgets the photos
    render_click(view, "clear")
    html = eventually(view, "Point at any stars")
    refute html =~ "Polar Axis"
  end

  test "move, snap, move, snap: the key never waits, and the rows say where each photo is", %{conn: conn, id: id, truth: truth} do
    :ok = Mount.set_home(id)
    :ok = Plates.set_workers(1)
    Stub.open(false)
    {:ok, view, _} = live(conn, "/align/photo/#{id}")

    for {ra, i} <- Enum.with_index([-30.0, 0.0, 30.0], 1) do
      snap = put_encoders(id, ra, -40.0)
      upload(view, "p#{i}.jpg", photo_of(truth, snap))
    end

    html = eventually(view, "Waiting, 1 ahead")
    assert html =~ "Waiting, next"
    assert html =~ ~r/Solving, \d+ s/
    assert html =~ "2 waiting, 1 solving"
    refute html =~ ~r/<label class="[^"]*take-photo off/

    Stub.open(true)
    html = eventually(view, "3 photos agree to")
    refute html =~ "Waiting"
  end

  test "the encoders are read when the photo is chosen, not when it finishes uploading", %{conn: conn, id: id, truth: truth} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/align/photo/#{id}")
    snap = put_encoders(id, -20.0, -35.0)
    input = file_input(view, "#photo-form", :photo, [%{name: "slow.jpg", content: photo_of(truth, snap), type: "image/jpeg"}])

    # half the photo arrives; the scope is already on its way to the next patch
    render_upload(input, "slow.jpg", 50)
    put_encoders(id, 40.0, -10.0)
    render(view)
    render_upload(input, "slow.jpg", 50)

    eventually(view, "Photo 1")
    [plate] = Plates.view(id).plates
    assert_in_delta plate.enc.ra_deg, -20.0, 1.0e-6
    assert_in_delta plate.enc.dec_deg, -35.0, 1.0e-6
  end

  test "failed photos read as advice, and can be retried or removed", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/align/photo/#{id}")
    put_encoders(id, 0.0, -40.0)
    upload(view, "dark.jpg", "P5 DARK")
    html = eventually(view, "Too few stars (needs about 15)")
    assert html =~ "Retry photo 1"

    render_click(view, "retry", %{"i" => "1"})
    eventually(view, "Too few stars (needs about 15)")
    render_click(view, "remove", %{"i" => "1"})
    refute eventually(view, "Point at any stars") =~ "Too few stars"
  end

  test "a photo chosen while the scope slews is kept but said to be moving", %{conn: conn, id: id} do
    :ok = Mount.set_home(id)
    {:ok, view, _} = live(conn, "/align/photo/#{id}")
    :ok = Mount.goto_relative(id, :ra, 30.0)
    assert_receive {:mount, %{axes: %{ra: %{goto_pending: true}}}}, 2_000
    render(view)
    upload(view, "p.jpg", "P5 STUB 10.0 45.0")
    html = eventually(view, "Telescope was moving: take it again")
    refute html =~ "Retry photo 1"
    Mount.emergency_stop(id)
  end

  test "no solver anywhere: one line says so, and the key is off", %{conn: conn, id: id} do
    if System.get_env("NOVA_API_KEY") == nil do
      Application.put_env(:controller, :solver, index_config: "/nowhere/astrometry.cfg")
      :ok = Mount.set_home(id)
      {:ok, view, _} = live(conn, "/align/photo/#{id}")
      html = render_async(view)
      assert html =~ "No plate solver on this machine or the cluster"
      assert html =~ ~r/<label class="[^"]*take-photo off/
    end
  end
end
