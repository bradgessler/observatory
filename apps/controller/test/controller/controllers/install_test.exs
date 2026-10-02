defmodule Controller.InstallTest do
  @moduledoc "Add to Home Screen: the manifest, the icons, and the tags iOS reads."
  use Controller.ConnCase, async: true

  test "the manifest is served as a manifest and names the icons", %{conn: conn} do
    conn = get(conn, "/manifest.webmanifest")
    assert conn.status == 200
    assert conn |> get_resp_header("content-type") |> hd() =~ "application/manifest+json"

    manifest = Jason.decode!(conn.resp_body)
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"

    for %{"src" => src} <- manifest["icons"] do
      assert get(build_conn(), src).status == 200, "#{src} is missing"
    end
  end

  test "every page says how to install it and draws under the notch", %{conn: conn} do
    html = conn |> get("/site") |> html_response(200)
    assert html =~ ~s(rel="manifest")
    assert html =~ ~s(rel="apple-touch-icon")
    assert get(build_conn(), "/images/apple-touch-icon.png").status == 200
    assert html =~ "viewport-fit=cover"
  end
end
