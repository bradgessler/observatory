defmodule Controller.RecoveryController do
  @moduledoc "The box's own record of each boot and each pick-up (`Controller.Recovery`), as JSON."
  use Controller, :controller

  def index(conn, params) do
    n = with %{"n" => v} <- params, {i, ""} <- Integer.parse(v), true <- i in 1..500, do: i, else: (_ -> 50)
    json(conn, Controller.Recovery.recent(n))
  end
end
