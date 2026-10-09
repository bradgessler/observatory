defmodule Controller.PadViewTest do
  @moduledoc "The pad's hat gets the Center page's view map, and a Backwards tap reaches it."
  use ExUnit.Case, async: false

  alias Controller.{PadView, Settings}

  test "a view map becomes the pad's eyepiece settings" do
    assert PadView.pad_map(%{"down" => ["ra", 1], "right" => ["dec", -1]}) ==
             %{hat: :eyepiece, view_down: {:ra, 1}, view_right: {:dec, -1}}
  end

  test "the running pad follows the setting, including a flip from any phone" do
    Settings.put("view_map", Controller.CenterLive.default_view_map())
    on_exit(fn -> Settings.put("view_map", Controller.CenterLive.default_view_map()) end)

    wait = fn want ->
      Enum.find_value(1..40, fn _ ->
        map = Input.Mapper.status().map
        if map[:hat] == :eyepiece and map[:view_down] == want, do: true, else: (Process.sleep(50) && nil)
      end)
    end

    send(PadView, :push)
    assert wait.({:ra, 1})

    Settings.put("view_map", Controller.CenterLive.flip(Controller.CenterLive.default_view_map(), "down"))
    assert wait.({:ra, -1})
  end
end
