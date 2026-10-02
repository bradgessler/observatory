defmodule Controller.StopController do
  @moduledoc """
  STOP from a page with no LiveView behind it (a help page): a form posts
  here, every mount in reach stops (`Controller.Stop.all/0`), and the page
  comes back. Only to a path on this site, never one a crafted link names.
  """
  use Controller, :controller

  def stop(conn, _params) do
    Controller.Stop.all()

    back =
      with [ref | _] <- get_req_header(conn, "referer"),
           %URI{path: "/" <> _ = path} <- URI.parse(ref),
           false <- String.starts_with?(path, "//") do
        path
      else
        _ -> "/"
      end

    redirect(conn, to: back)
  end
end
