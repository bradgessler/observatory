defmodule Controller.VideoController do
  @moduledoc "Serves the HLS playlist and segments `Video` writes. Names are whitelisted; nothing else under that directory is reachable."
  use Controller, :controller

  def file(conn, %{"quality" => q, "name" => name}) do
    with %{id: id} <- Video.Ladder.parse(q),
         true <- name == "index.m3u8" or Regex.match?(~r/^seg\d{1,8}\.ts$/, name),
         path = Path.join(Video.HLS.dir(id), name),
         true <- File.regular?(path) do
      {type, cache} =
        if name == "index.m3u8",
          do: {"application/vnd.apple.mpegurl", "no-store"},
          else: {"video/mp2t", "private, max-age=60"}

      conn
      |> put_resp_content_type(type)
      |> put_resp_header("cache-control", cache)
      |> send_file(200, path)
    else
      _ -> conn |> put_status(:not_found) |> text("no such file")
    end
  end
end
