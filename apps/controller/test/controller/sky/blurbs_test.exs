defmodule Controller.Sky.BlurbsTest do
  @moduledoc """
  What an object is, in a sentence or two. The pages show these words as
  they are written (#150: the Tonight panel used to swap the em dashes for
  commas as it drew them), so the words themselves keep to the UI's rules.
  """
  use ExUnit.Case, async: true

  alias Controller.Sky.Blurbs

  test "no em dashes or en dashes: commas, colons and full stops" do
    for text <- Blurbs.all() do
      refute text =~ ~r/[—–]/u, text
    end
  end

  test "each starts with a sentence that stands by itself, so the first two can be shown alone" do
    for text <- Blurbs.all() do
      [first | _] = String.split(text, ~r/(?<=[.!?])\s+/)
      assert first =~ ~r/^[A-Z].*[.!?]$/su, text
    end
  end

  test "an object the catalogue has words for gets them; anything else, its kind's" do
    assert Blurbs.for(%{id: "m31", kind: :galaxy}) =~ "Andromeda Galaxy: the farthest thing"
    assert Blurbs.for(%{id: "nothing-by-this-name", kind: :galaxy}) =~ "A galaxy:"
    assert Blurbs.for(%{id: "nothing-by-this-name", kind: :comet}) == ""
  end
end
