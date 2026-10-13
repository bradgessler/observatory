defmodule Controller.KindIconsTest do
  @moduledoc """
  What kind of thing an object is, drawn (`Icons.kind/1`), wherever objects
  are listed (#150). Tonight's rows, the picked object's panel and Details
  had it; the Recent chips above Tonight's list and the Status page's Look At
  list did not.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Model, Pointing, Stars}

  setup do
    id = "sim-kind-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000

    on_exit(fn ->
      Lineup.clear(id)
      Settings.put("recent_targets", Map.delete(Settings.get("recent_targets", %{}), id))
    end)

    %{id: id}
  end

  # what is remembered of a Go To is its id and name only: the kind comes from the catalogue
  test "a Recent chip on Tonight carries its object's kind", %{conn: conn, id: id} do
    recent = [
      %{"id" => "m31", "name" => "M31 Andromeda"},
      %{"id" => "sol-saturn", "name" => "Saturn"},
      %{"id" => "sol-moon", "name" => "Moon"},
      %{"id" => "gone-from-the-catalogue", "name" => "Something"}
    ]

    Settings.put("recent_targets", Map.put(Settings.get("recent_targets", %{}), id, recent))

    {:ok, view, _html} = live(conn, "/tonight/#{id}")
    assert has_element?(view, ~s(nav.recent a[href^="/object/m31?"] svg.kind-icon[aria-label="Galaxy"]))
    assert has_element?(view, ~s(nav.recent a[href^="/object/sol-saturn?"] svg.kind-icon[aria-label="Planet"]))
    assert has_element?(view, ~s(nav.recent a[href^="/object/sol-moon?"] svg.kind-icon[aria-label="The Moon"]))
    # a target the catalogue does not know: its name alone, and no empty box beside it
    assert has_element?(view, ~s(nav.recent a[href^="/object/gone-from-the-catalogue?"]), "Something")
    refute has_element?(view, ~s(nav.recent a[href^="/object/gone-from-the-catalogue?"] svg))
  end

  test "every row of the Status page's Look At list draws its kind before the name", %{conn: conn, id: id} do
    # aligned, so the page is on its last step: a known alignment from three stars
    :ok = Mount.set_home(id)
    truth = %{axis_alt: 43.9, axis_az: 330.0, off_ra: 12.0, off_dec: -4.0}
    now = DateTime.utc_now()
    site = Pointing.site()

    for name <- ["Vega", "Altair", "Arcturus"] do
      star = Enum.find(Stars.all(), &(&1.name == name))
      {alt, az} = Astro.alt_az(star.ra_deg, star.dec_deg, site.lat, Astro.lst_deg(now, site.lon))
      {r, d} = Model.encoders(truth, Pointing.pointing(), alt, az)
      Lineup.add(%{id: id, homed: true, connected: true, tracking: :off, axes: %{ra: %{degrees: r}, dec: %{degrees: d}}}, star, now)
    end

    {:ok, view, html} = live(conn, "/alignment/#{id}")
    assert html =~ "Look At"

    list = ~s(ul.items[aria-label="tonight's targets"])
    assert has_element?(view, "#{list} > li.item.item-kind > .item-k:first-child > svg.kind-icon[role=img]")
    refute has_element?(view, "#{list} > li.item:not(.item-kind)")
  end
end
