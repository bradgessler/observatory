defmodule Controller.ScopeCameraController do
  @moduledoc "Serves the telescope camera's latest frame, and its brightest star up close, as PNGs."
  use Controller, :controller

  alias Controller.ScopeCamera

  @doc "The latest picture: this machine's, or with `node=` a box's, fetched across the cluster (the Mac showing a box's camera)."
  def frame(conn, %{"node" => name}) do
    with node when node != node() <- ScopeCamera.node_named(name),
         %{png: png} when is_binary(png) <- safe_erpc(node, :latest, []) do
      conn |> put_resp_content_type("image/png") |> put_resp_header("cache-control", "no-store") |> send_resp(200, png)
    else
      n when n == node() -> frame(conn, %{})
      _ -> conn |> put_status(:not_found) |> text("no frame yet")
    end
  end

  def frame(conn, _params), do: send_png(conn, fn f -> f.png end)

  @doc "One of the last frames, by number (with `node=`, a box's)."
  def numbered(conn, %{"seq" => seq} = params) do
    with {n, ""} <- Integer.parse(seq), {:ok, _record, png} <- ScopeCamera.frame(n, ScopeCamera.node_named(params["node"])) do
      conn |> put_resp_content_type("image/png") |> put_resp_header("cache-control", "max-age=3600") |> send_resp(200, png)
    else
      _ -> conn |> put_status(:not_found) |> text("that frame is gone")
    end
  end

  def star(conn, _params), do: send_png(conn, fn f -> f.star_png end)

  defp safe_erpc(node, fun, args) do
    :erpc.call(node, ScopeCamera, fun, args, 5_000)
  catch
    _, _ -> nil
  end

  defp send_png(conn, pick) do
    case ScopeCamera.latest() do
      %{} = frame when is_binary(frame.png) ->
        case pick.(frame) do
          png when is_binary(png) ->
            conn
            |> put_resp_content_type("image/png")
            |> put_resp_header("cache-control", "no-store")
            |> send_resp(200, png)

          _ ->
            conn |> put_status(:not_found) |> text("no star")
        end

      _ ->
        conn |> put_status(:not_found) |> text("no frame yet")
    end
  end
end
