defmodule Controller.RedirectController do
  @moduledoc """
  A page that moved: its old path answers with a permanent redirect to the
  new one, the rest of the path and the query carried over, so a bookmark on
  a phone keeps working (`/scope-camera/focus` → `/cameras/telescope/focus`).
  The router gives the new home as `assigns: %{to: path}`.
  """
  use Controller, :controller

  # what each of the bench's surfaces was, at its own address (with the mount it was on)
  @bench %{
    "strips" => "/keypad",
    "tilt" => "/keypad",
    "align" => "/controls/align",
    "dpad" => "/controls/dpad",
    "nudge" => "/controls/nudge",
    "eyepiece" => "/controls/eyepiece",
    "scope" => "/controls/scope",
    "orb" => "/controls/orb",
    "center" => "/controls/center",
    "position" => "/controls/position",
    "gamepad" => "/input",
    "watch" => "/cameras/observatory",
    "sky" => "/sky"
  }
  @with_id ~w(/keypad /controls/align /controls/dpad /controls/nudge /controls/eyepiece /controls/scope /controls/orb /controls/center /controls/position /sky)

  @doc "The bench's old addresses (`/bench/sky?mount=eq6r`): the page itself (`/sky/eq6r`); `/bench` alone, Home."
  def bench(conn, params) do
    to =
      case {Map.get(@bench, params["surface"]), params["mount"]} do
        {nil, _} -> "/"
        {path, id} when is_binary(id) and id != "" ->
          if path in @with_id, do: path <> "/" <> URI.encode(id), else: path <> "?" <> URI.encode_query(mount: id)

        {path, _} -> path
      end

    conn |> put_status(:moved_permanently) |> redirect(to: to)
  end

  def moved(conn, params) do
    rest = Enum.join(params["rest"] || [], "/")
    to = if rest == "", do: conn.assigns.to, else: conn.assigns.to <> "/" <> rest
    to = if conn.query_string == "", do: to, else: to <> "?" <> conn.query_string

    conn
    |> put_status(:moved_permanently)
    |> redirect(to: to)
  end
end
