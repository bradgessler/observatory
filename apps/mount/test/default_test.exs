defmodule Mount.DefaultTest do
  @moduledoc """
  The mount a page drives when none was asked for. A Mac with no cable runs a
  simulator, and a box's telescope joined over the network must win over it.
  """
  use ExUnit.Case, async: true

  test "a real telescope before a simulator, whatever the names sort to" do
    assert Mount.default(["sim-eq", "ttyUSB0"]) == "ttyUSB0"
    assert Mount.default([%{id: "sim-eq", node: :a@mac}, %{id: "ttyUSB0", node: :telescope@box}]) == %{id: "ttyUSB0", node: :telescope@box}
  end

  test "among real ones, by id; only a simulator, the simulator; none, nothing" do
    assert Mount.default(["ttyUSB1", "ttyUSB0", "sim-eq"]) == "ttyUSB0"
    assert Mount.default(["sim-eq"]) == "sim-eq"
    assert Mount.default([]) == nil
  end

  test "another machine's simulator is not listed here; its real telescopes are" do
    here = :"observatory@mac.local"
    assert Mount.listed?(%{id: "sim-eq", node: here}, here)
    refute Mount.listed?(%{id: "sim-eq", node: :"telescope@observatory.local"}, here)
    assert Mount.listed?(%{id: "ttyUSB0", node: :"telescope@observatory.local"}, here)
  end
end
