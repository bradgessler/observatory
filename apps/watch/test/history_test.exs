defmodule Watch.HistoryTest do
  use ExUnit.Case, async: false

  setup do
    Watch.History.clear()
    :ok
  end

  defp frame(ms_ago, bytes \\ 2_000) do
    at = DateTime.add(DateTime.utc_now(), -ms_ago, :millisecond)
    %{jpeg: :binary.copy(<<0xFF>>, bytes), at: at, device: "t", bytes: bytes}
  end

  test "frames are written under a sortable name and listed newest first" do
    {:ok, a} = Watch.History.put(frame(2_000))
    {:ok, b} = Watch.History.put(frame(1_000))
    assert Watch.History.valid_name?(a.name)
    assert [^b, ^a] = Watch.History.list()
    assert {:ok, <<0xFF, _::binary>>} = Watch.History.read(a.name)
    assert [^b] = Watch.History.list(limit: 1)
    assert [^b] = Watch.History.list(since: DateTime.add(DateTime.utc_now(), -1_500, :millisecond))
  end

  test "frames older than the window are pruned from disk" do
    max_age_ms = Watch.History.policy().max_age_s * 1_000
    {:ok, old} = Watch.History.put(frame(max_age_ms + 5_000))
    {:ok, fresh} = Watch.History.put(frame(0))
    assert [^fresh] = Watch.History.list()
    assert {:error, :not_found} = Watch.History.read(old.name)
    refute File.exists?(Path.join(Watch.History.dir(), old.name))
  end

  test "names are validated before touching the filesystem" do
    assert {:error, :not_found} = Watch.History.read("../../etc/passwd")
    assert {:error, :not_found} = Watch.History.read("nope.jpg")
  end

  test "summary reports the window in force" do
    assert %{count: 0, bytes: 0, policy: %{max_frames: _}} = Watch.History.summary()
    Watch.History.put(frame(0))
    assert %{count: 1} = Watch.History.summary()
  end
end
