defmodule Stamp.ConnCase do
  @moduledoc "Connection tests for the Stamp a Box pages, against the controller's endpoint they plug into."
  use ExUnit.CaseTemplate

  using do
    quote do
      @endpoint Controller.Endpoint

      use Controller, :verified_routes

      import Plug.Conn
      import Phoenix.ConnTest
    end
  end

  setup _tags do
    {:ok, conn: Phoenix.ConnTest.build_conn()}
  end
end
