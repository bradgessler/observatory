defmodule Controller.DatabaseTest do
  @moduledoc """
  The database (#107): settings in it a row per key, a settings.json from
  before brought in once, and the JSON file again whenever the database is
  down; the frames spool's index in it, surviving a restart, bringing in
  the .meta files from before, and never touching another spool's rows.
  """
  use ExUnit.Case, async: false

  import Ecto.Query
  alias Controller.{Repo, Settings}
  alias Controller.Frames.{Frame, SpoolIndex}
  alias Queues.Spool

  test "the database is up and migrated, and the settings live in it" do
    assert Repo.up?()
    assert Settings.store() == :database
    :ok = Settings.put("db_test_key", %{"a" => [1, 2.5, "x"]})
    assert Settings.get("db_test_key") == %{"a" => [1, 2.5, "x"]}
    assert Repo.one(from s in "settings", where: s.key == "db_test_key", select: s.value) == ~s({"a":[1,2.5,"x"]})
  end

  test "a settings.json from before the database is brought in once and kept beside" do
    path = Application.get_env(:controller, :settings_path)
    Repo.delete_all("settings")
    File.write!(path, Jason.encode!(%{"site" => %{"lat" => 37.5, "lon" => -122.0}, "night" => true}))

    map = Settings.load()
    assert map["site"] == %{"lat" => 37.5, "lon" => -122.0} and map["night"] == true
    assert Repo.aggregate(from(s in "settings"), :count) == 2
    refute File.exists?(path)
    assert File.exists?(path <> ".imported")
    # the second time it comes from the database
    assert Settings.load()["night"] == true

    # a settings.json that turns up again (written while the database was down) adds what's missing, and the database wins
    File.write!(path, Jason.encode!(%{"night" => false, "late" => 1}))
    map = Settings.load()
    assert map["night"] == true and map["late"] == 1
    assert Repo.aggregate(from(s in "settings"), :count) == 3
  after
    File.rm(Application.get_env(:controller, :settings_path) <> ".imported")
  end

  test "with the database down, settings carry on from and to the JSON file" do
    path = Application.get_env(:controller, :settings_path)
    :persistent_term.put({Repo, :migrated}, false)
    assert Settings.store() == :json
    :ok = Settings.put("while_down", 7)
    assert Jason.decode!(File.read!(path))["while_down"] == 7
    assert Settings.get("while_down") == 7
  after
    :persistent_term.put({Repo, :migrated}, true)
    File.rm(Application.get_env(:controller, :settings_path))
  end

  describe "the frames spool's index" do
    setup do
      dir = Path.join(System.tmp_dir!(), "spool-db-#{System.unique_integer([:positive])}")
      on_exit(fn -> File.rm_rf(dir) end)
      %{dir: dir, name: "db-spool-#{System.unique_integer([:positive])}"}
    end

    test "rows follow the files: put, lease, ack, and a restart reads them back", %{dir: dir, name: name} do
      start_supervised!({Spool, name: name, dir: dir, index: SpoolIndex, budget_bytes: 1_000_000, min_free_bytes: 0})
      record = %{seq: 42, at: DateTime.utc_now(), why: "picture", exposure_ms: 1000, gain: 80, stack: 4, stars: 12, hfr_px: 2.1, verdict: :stars}
      {:ok, _} = Spool.put(name, "100-1.fits", "pixels", %{seq: 42, record: record})
      {:ok, _} = Spool.put(name, "100-2.fits", "more", %{seq: 43, record: %{record | seq: 43}})

      row = Repo.one(from f in Frame, where: f.place == "spool" and f.id == "100-1.fits")
      assert row.state == "ready" and row.seq == 42 and row.stars == 12 and row.verdict == "stars" and row.gain == 80
      assert row.path == Path.join(dir, "100-1.fits")

      [%{id: "100-1.fits"}] = Spool.lease(name, 1)
      :ok = Spool.ack(name, "100-1.fits")
      assert Repo.one(from f in Frame, where: f.id == "100-1.fits", select: f.state) == "sent"

      stop_supervised!({Spool, name})
      start_supervised!({Spool, name: name, dir: dir, index: SpoolIndex, budget_bytes: 1_000_000, min_free_bytes: 0})
      assert [%{id: "100-2.fits"}] = Spool.lease(name, 5)
    end

    test ".meta files from before the database are brought in and removed", %{dir: dir, name: name} do
      File.mkdir_p!(dir)
      File.write!(Path.join(dir, "200-1.fits"), "old")
      Queues.Spool.Files.put(name, dir, %{id: "200-1.fits", bytes: 3, sha256: "x", meta: %{seq: 1}, at_ms: 1, state: :ready})

      start_supervised!({Spool, name: name, dir: dir, index: SpoolIndex, budget_bytes: 1_000_000, min_free_bytes: 0})
      refute File.exists?(Path.join(dir, "200-1.fits.meta"))
      assert Repo.one(from f in Frame, where: f.place == "spool" and f.id == "200-1.fits", select: f.state) == "ready"
      assert [%{id: "200-1.fits"}] = Spool.lease(name, 1)
    end

    test "a spool never touches another spool's rows", %{dir: dir, name: name} do
      other = Path.join(System.tmp_dir!(), "other-spool-#{System.unique_integer([:positive])}")
      File.mkdir_p!(other)
      File.write!(Path.join(other, "300-1.fits"), "theirs")
      :ok = SpoolIndex.put("other", other, %{id: "300-1.fits", bytes: 6, sha256: "y", meta: %{}, at_ms: 1, state: :ready})

      start_supervised!({Spool, name: name, dir: dir, index: SpoolIndex, budget_bytes: 1_000_000, min_free_bytes: 0})
      assert Repo.one(from f in Frame, where: f.place == "spool" and f.id == "300-1.fits", select: f.state) == "ready"
    after
      Repo.delete_all(from f in Frame, where: f.id == "300-1.fits")
    end
  end
end
