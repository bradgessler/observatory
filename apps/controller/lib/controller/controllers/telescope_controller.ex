defmodule Controller.TelescopeController do
  @moduledoc """
  Switches the telescope this viewer is driving, then goes back to the page
  they were on (`?return=`), or to Home.

  The choice is per viewer, like the tab they are on: kept in their session,
  not in the mount or settings. The Mac, a phone and the box's own page can
  each have a different telescope current, and every page uses it unless a
  link names one (`?mount=`, `/:id`).
  """
  use Controller, :controller

  def use(conn, %{"id" => id} = params) do
    conn
    |> put_session("telescope", id)
    |> redirect(to: return_to(params["return"]))
  end

  # only a path on this site: never somewhere a crafted link names
  defp return_to("/" <> rest = path) do
    if String.starts_with?(rest, "/") or String.contains?(path, "\\"), do: ~p"/", else: path
  end

  defp return_to(_), do: ~p"/"
end
