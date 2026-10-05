defmodule Controller.StillCameraController do
  @moduledoc """
  Serves the stills camera's last picture (its small grey copy) as a PNG, and
  the pictures themselves: the nights kept, a night's files, and each file as
  the camera made it (RAW, JPEG) or as the box wrote it (the `.json` sidecar,
  `index.jsonl`). This is how pictures leave the box: any HTTP client can
  copy a night.
  """
  use Controller, :controller

  def latest(conn, _params) do
    case Controller.StillCamera.png() do
      png when is_binary(png) ->
        conn
        |> put_resp_content_type("image/png")
        |> put_resp_header("cache-control", "no-store")
        |> send_resp(200, png)

      _ ->
        conn |> put_status(:not_found) |> text("no picture yet")
    end
  end

  @doc "The nights kept, newest first: `[%{night, files, bytes}]`."
  def nights(conn, _params) do
    dir = Controller.StillCamera.dir()

    nights =
      for night <- list(dir), night =~ ~r/^\d{4}-\d{2}-\d{2}$/ do
        files = list(Path.join(dir, night))
        %{night: night, files: length(files), bytes: files |> Enum.map(&size(Path.join([dir, night, &1]))) |> Enum.sum()}
      end

    json(conn, Enum.sort_by(nights, & &1.night, :desc))
  end

  @doc "A night's files: `[%{name, bytes}]`, in name (so time) order."
  def night(conn, %{"night" => night}) do
    with true <- night =~ ~r/^\d{4}-\d{2}-\d{2}$/,
         dir = Path.join(Controller.StillCamera.dir(), night),
         true <- File.dir?(dir) do
      json(conn, for(name <- list(dir), do: %{name: name, bytes: size(Path.join(dir, name))}))
    else
      _ -> conn |> put_status(:not_found) |> text("no such night")
    end
  end

  @doc "One file, whole. Only a plain file name inside a night's folder is ever read."
  def file(conn, %{"night" => night, "name" => name}) do
    path = Path.join([Controller.StillCamera.dir(), night, name])

    if night =~ ~r/^\d{4}-\d{2}-\d{2}$/ and name == Path.basename(name) and not String.starts_with?(name, ".") and File.regular?(path) do
      conn
      |> put_resp_content_type(MIME.from_path(String.downcase(name)), nil)
      |> put_resp_header("cache-control", "no-store")
      |> send_file(200, path)
    else
      conn |> put_status(:not_found) |> text("no such file")
    end
  end

  defp list(dir) do
    case File.ls(dir) do
      {:ok, names} -> Enum.sort(names)
      _ -> []
    end
  end

  defp size(path) do
    case File.stat(path) do
      {:ok, %{size: n}} -> n
      _ -> 0
    end
  end
end
