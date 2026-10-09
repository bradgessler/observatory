defmodule Controller.SpiralTest do
  @moduledoc """
  Spiral Search sized by what we know (#100): views a bit under the
  eyepiece's field apart, out to three times the alignment's margin, with a
  count on the page; I See It ends it.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-sp-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "no alignment to judge by: the widest square, views 50′ apart through a 72′ eyepiece", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/object/m13?mount=#{id}")
    html = render_click(view, "search", %{})
    assert html =~ "Spiral Search: view 0 of 80, 50′ apart"
    assert html =~ "I See It"

    html = render_click(view, "search_found", %{})
    refute html =~ "Spiral Search: view"
  after
    Mount.stop(id)
  end
end
