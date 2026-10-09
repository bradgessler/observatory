defmodule Controller.SpoolController do
  @moduledoc """
  A file waiting in one of this machine's spools (`Queues.Spool`), for the
  Mac to copy: sent straight from disk, never read into memory, so a 50 MB
  raw frame costs the box nothing but the card and the network.
  """
  use Controller, :controller

  def show(conn, %{"name" => name, "id" => id}) do
    with true <- safe?(name) and safe?(id),
         {:ok, path} <- Queues.Spool.path(name, id) do
      conn
      |> put_resp_content_type("application/octet-stream")
      |> send_file(200, path)
    else
      _ -> send_resp(conn, 404, "not here")
    end
  end

  defp safe?(s), do: s =~ ~r/\A[\w.\-]+\z/ and not String.contains?(s, "..")
end
