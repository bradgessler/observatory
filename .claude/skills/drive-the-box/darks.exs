# Dark frames: the camera only, with the lens cap on (Brad puts it on and says so; this script cannot tell a cap
# from a cloud). DARKS="15:3200:20,4:1600:10" takes 20 darks at 15 s ISO 3200 and 10 at 4 s ISO 1600: the same
# exposures and ISOs as the night's light frames, ideally right after them while the camera is at the night's
# temperature. Each is marked a dark in its sidecar ("frame": {"type": "dark"}) so the stacking tools find it
# (`stack-pictures/tools/darks.py`). It refuses if the frames are not dark (a sky left uncovered), never touches the
# mount, runs on the box by itself and logs "darks: ...". Stop it with send(:darks_runner, :stop).
alias Controller.StillCamera
if pid = Process.whereis(:darks_runner), do: Process.exit(pid, :kill)

sets =
  (System.get_env("DARKS") || "15:3200:20")
  |> String.split(",", trim: true)
  |> Enum.map(fn s -> [sh, iso, n] = String.split(s, ":"); {sh, String.to_integer(iso), String.to_integer(n)} end)

runner = fn ->
  require Logger
  Process.register(self(), :darks_runner)
  say = fn words -> Logger.warning("darks: " <> words) end
  stopped? = fn -> receive do :stop -> true after 0 -> false end end

  take = fn ->
    before = (StillCamera.status().last || %{})[:seq] || 0
    StillCamera.shoot(frame: :dark)
    Enum.find_value(1..200, fn _ ->
      Process.sleep(1000)
      s = StillCamera.status()
      if not s.busy and s.last && s.last[:seq] > before, do: s.last
    end)
  end

  StillCamera.continuous(false)

  result =
    Enum.reduce_while(sets, :ok, fn {shutter, iso, n}, _ ->
      StillCamera.set(iso: iso, shutter: shutter)
      first = take.()
      bg = first && first[:background]

      cond do
        # a dark frame's grey copy sits at the bottom: anything brighter is light getting in
        not is_number(bg) -> {:halt, {:no_picture, shutter, iso}}
        bg > 12 -> say.("#{shutter} s ISO #{iso} reads #{bg} of 255: that is not dark (is the cap on?). Stopping."); {:halt, {:not_dark, bg}}
        true ->
          say.("#{shutter} s ISO #{iso}: 1 of #{n}, reads #{bg}")
          done = Enum.reduce_while(2..max(n, 2)//1, 1, fn i, k -> if stopped?.(), do: {:halt, k}, else: (take.(); say.("#{shutter} s ISO #{iso}: #{i} of #{n}"); {:cont, i}) end)
          if done < n, do: {:halt, :asked}, else: {:cont, :ok}
      end
    end)

  StillCamera.set(iso: 6400, shutter: "2")
  say.("finished: #{inspect(result)}")
end

pid = spawn(runner)
IO.puts("S darks runner #{inspect(pid)}: #{inspect(sets)}")
Process.sleep(300)
