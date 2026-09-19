defmodule Controller.WatchController do
  @moduledoc "Serves the latest frame from `Watch` as a JPEG."
  use Controller, :controller

  def latest(conn, _params) do
    case Watch.latest() do
      %{jpeg: jpeg, at: at} ->
        conn
        |> put_resp_content_type("image/jpeg")
        |> put_resp_header("cache-control", "no-store")
        |> put_resp_header("x-captured-at", DateTime.to_iso8601(at))
        |> send_resp(200, jpeg)

      nil ->
        conn |> put_status(:not_found) |> text("no frame yet")
    end
  end

  # A named frame from the history never changes, so it may be cached hard.
  def frame(conn, %{"name" => name}) do
    case Watch.frame(name) do
      {:ok, jpeg} ->
        conn
        |> put_resp_content_type("image/jpeg")
        |> put_resp_header("cache-control", "private, max-age=3600, immutable")
        |> send_resp(200, jpeg)

      {:error, _} ->
        conn |> put_status(:not_found) |> text("no such frame")
    end
  end
end
