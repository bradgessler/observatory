defmodule Controller.WordsTest do
  @moduledoc "What a page says for an error, an unknown value, a node and a title: words, never a raw term."
  use ExUnit.Case, async: true

  alias Controller.Words

  doctest Controller.Words

  describe "error/1" do
    test "the common reasons are plain sentences" do
      assert Words.error(:timeout) == "Timed out waiting for an answer"
      assert Words.error(:not_connected) == "Mount not connected"
      assert Words.error(:no_mount) == "No mount"
      assert Words.error(:closed) == "Connection closed"
      assert Words.error(:enoent) == "Not found on this machine"
      assert Words.error(:busy) == "Busy, try again in a moment"
      assert Words.error(:limit) == "Soft limit"
    end

    test "{:error, reason} and exits unwrap to the reason" do
      assert Words.error({:error, :timeout}) == Words.error(:timeout)
      assert Words.error({:error, {:error, :busy}}) == Words.error(:busy)
      assert Words.error({:timeout, {GenServer, :call, [self(), :snapshot, 5000]}}) == Words.error(:timeout)
    end

    test "the mount driver's {cmd, axis, reason} says what the mount did" do
      assert Words.error({"j", :ra, :timeout}) == Words.error(:timeout)
      assert Words.error({"G", :dec, :motor_running}) == "Still moving"
      assert Words.error({:garbage, "?x"}) == "The mount sent a garbled reply"
    end

    test "a string passes through as a sentence" do
      assert Words.error("Photo too dark") == "Photo too dark"
      assert Words.error("no stars found") == "No stars found"
    end

    test "an exception gives its message" do
      assert Words.error(%RuntimeError{message: "camera unplugged"}) == "Camera unplugged"
    end

    test "anything else is readable words, never inspect output" do
      assert Words.error(:no_ffmpeg) == "Something went wrong (no ffmpeg)"
      assert Words.error({:bad_reply, 42}) == "Something went wrong (bad reply 42)"
      assert Words.error(~c"port closed") == "Something went wrong (port closed)"
    end

    test "pids, refs, maps and structs are never shown" do
      for term <- [self(), make_ref(), %{a: 1}, URI.parse("http://x"), {self(), make_ref()}] do
        said = Words.error(term)
        assert said == "Something went wrong"
        refute said =~ "#PID" or said =~ "%"
      end
    end
  end

  test "none/0 is a word, not a dash" do
    assert Words.none() == "Unknown"
  end

  test "host/1 is the machine's name from a node" do
    assert Words.host(:"telescope@observatory.local") == "observatory"
    assert Words.host(:"controller@studio") == "studio"
    assert Words.host(:nonode@nohost) == "nohost"
  end

  test "title/2 never leaves a dangling separator" do
    assert Words.title("eq6r", "Nudge") == "eq6r · Nudge"
    assert Words.title(nil, "Nudge") == "Nudge"
    assert Words.title("", "Nudge") == "Nudge"
  end
end
