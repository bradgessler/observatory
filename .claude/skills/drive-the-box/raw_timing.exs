# Does RAW only shorten the time between pictures? The camera only, the mount untouched; not while a plan runs.
# Takes N pictures at 1/60 s as RAW+JPEG, then N as RAW alone, and compares, from each picture's own sidecar,
# exposure end to "picture ready" (the camera's own processing: 12.2 s on 17 October) and ready to saved (the
# download). Puts the camera's quality back as it found it.
#   N=6 box - < raw_timing.exs | grep '^R'
# 18 October 2026, Brad: "I mostly want to cut latency. If getting rid of jpg doesn't do that, don't bother."
alias Controller.StillCamera
n = String.to_integer(System.get_env("N") || "6")

if Process.whereis(:plan_runner) do
  IO.puts("R a plan is running: not now")
else
  StillCamera.continuous(false)
  was = StillCamera.status()[:camera][:settings][:quality]
  {:ok, _} = StillCamera.set(iso: 800, shutter: "1/60")

  idle = fn idle, k -> if StillCamera.status().busy and k > 0, do: (Process.sleep(500); idle.(idle, k - 1)), else: :ok end

  one = fn ->
    idle.(idle, 120)
    before = (StillCamera.status().last || %{})[:seq]
    StillCamera.shoot()
    w = fn w, k -> l = StillCamera.status().last || %{}; if l[:seq] == before and k > 0, do: (Process.sleep(500); w.(w, k - 1)), else: l end
    l = w.(w, 120)
    idle.(idle, 120)
    t = Jason.decode!(File.read!(l.base <> ".json"))["time"]
    ts = fn k -> {:ok, d, _} = DateTime.from_iso8601(t[k]); d end
    {DateTime.diff(ts.("picture_ready"), ts.("exposure_end"), :millisecond), DateTime.diff(ts.("saved"), ts.("picture_ready"), :millisecond), length(l.names)}
  end

  med = fn xs -> xs |> Enum.sort() |> Enum.at(div(length(xs), 2)) end

  for {q, label} <- [{19, "RAW+JPEG"}, {16, "RAW alone"}] do
    case StillCamera.set(quality: q) do
      {:ok, %{settings: %{quality: got}}} ->
        # one picture to settle the new setting, not counted
        one.()
        runs = for _ <- 1..n, do: one.()
        IO.puts("R #{label} (camera says #{got}): ready #{med.(Enum.map(runs, &elem(&1, 0)))} ms after the exposure, saved #{med.(Enum.map(runs, &elem(&1, 1)))} ms later, #{elem(hd(runs), 2)} files; each: #{inspect(runs)}")

      other ->
        IO.puts("R #{label}: the camera refused the setting: #{inspect(other)}")
    end
  end

  back = case was do "RAW" -> 16; "RAW+JPEG" -> 19; "JPEG Fine" -> 3; "JPEG Standard" -> 2; _ -> 19 end
  IO.puts("R quality back to #{inspect(StillCamera.set(quality: back) |> then(fn {:ok, s} -> s.settings.quality; e -> e end))}")
end
