defmodule Controller.ScopeCamera.Device do
  @moduledoc """
  The telescope camera itself: a USB "UVC" camera (the SVBONY SV105 and most
  planetary cameras), found, set and read without a vendor driver.

  **Finding it.** On the Pi, the kernel's `uvcvideo` driver makes it
  `/dev/videoN`; the Pi's own video blocks (`bcm2835-*`) are there too and
  are skipped. On a Mac it's an avfoundation device, found the way the
  Watch video finds cameras.

  **Setting it.** `v4l2-ctl` (Linux): exposure to manual and a length in
  milliseconds, and gain. A UVC camera keeps its controls while it's
  powered, so they're set once and on every change, not per frame.

  **Reading it** is `Controller.ScopeCamera.Stream`'s: one ffmpeg, kept
  open, with `input_args/2` from here.
  """


  @doc "Telescope cameras on this machine: `[%{id, name, path}]`."
  def list do
    case :os.type() do
      {:unix, :linux} -> linux()
      {:unix, :darwin} -> darwin()
      _ -> []
    end
  end

  # every capture node the uvcvideo driver owns (a UVC camera also has a
  # metadata node, index 1, which can't give frames)
  defp linux do
    "/sys/class/video4linux/video*"
    |> Path.wildcard()
    |> Enum.flat_map(fn sys ->
      node = Path.basename(sys)
      driver = with {:ok, link} <- File.read_link(Path.join(sys, "device/driver")), do: Path.basename(link), else: (_ -> nil)
      index = sys |> Path.join("index") |> File.read() |> case do {:ok, i} -> String.trim(i); _ -> "0" end
      name = sys |> Path.join("name") |> File.read() |> case do {:ok, n} -> tidy(String.trim(n)); _ -> node end

      if driver == "uvcvideo" and index == "0", do: [%{id: "/dev/" <> node, name: name, path: "/dev/" <> node}], else: []
    end)
    |> Enum.sort_by(& &1.id)
  end

  # UVC names often say themselves twice ("SVBONY SV105C: SVBONY SV105C")
  defp tidy(name) do
    case String.split(name, ": ", parts: 2) do
      [a, a] -> a
      _ -> name
    end
  end

  defp darwin do
    Video.Source.Local.devices()
    |> Enum.map(fn %{id: idx, name: name} -> %{id: idx, name: name, path: idx} end)
  rescue
    _ -> []
  end

  @doc "Make sure the kernel driver is loaded (it loads itself on plug-in; this is for a camera plugged in before boot)."
  def load_driver do
    with {:unix, :linux} <- :os.type(),
         exe when is_binary(exe) <- System.find_executable("modprobe") do
      System.cmd(exe, ["uvcvideo"], stderr_to_stdout: true)
    end

    :ok
  end

  @doc """
  Who the camera is, for the record: `%{driver, card, bus, serial, usb_id}`
  from `v4l2-ctl --info` and the USB ids in sysfs. Empty where there's no
  v4l2-ctl (a Mac).
  """
  def info(path) do
    with exe when is_binary(exe) <- System.find_executable("v4l2-ctl"),
         {out, 0} <- System.cmd(exe, ["-d", path, "--info"], stderr_to_stdout: true) do
      field = fn name -> with [_, v] <- Regex.run(~r/#{name}\s*:\s*(.+)/, out), do: String.trim(v), else: (_ -> nil) end
      usb = Path.join(["/sys/class/video4linux", Path.basename(path), "device", ".."])
      id = fn f -> with {:ok, v} <- File.read(Path.join(usb, f)), do: String.trim(v), else: (_ -> nil) end

      %{
        driver: [field.("Driver name"), field.("Driver version")] |> Enum.reject(&is_nil/1) |> Enum.join(" "),
        card: field.("Card type"),
        bus: field.("Bus info"),
        serial: field.("Serial"),
        usb_id: if(id.("idVendor"), do: "#{id.("idVendor")}:#{id.("idProduct")}")
      }
    else
      _ -> %{}
    end
  end

  # -- controls ----------------------------------------------------------------------------

  @doc """
  The camera's controls as `v4l2-ctl --list-ctrls` reports them:
  `%{"gain" => %{type: "int", min: 0, max: 100, value: 32}, ...}`. Empty
  where there's no v4l2-ctl (a Mac).
  """
  def controls(path) do
    with exe when is_binary(exe) <- System.find_executable("v4l2-ctl"),
         {out, 0} <- System.cmd(exe, ["-d", path, "--list-ctrls"], stderr_to_stdout: true) do
      parse_controls(out)
    else
      _ -> %{}
    end
  end

  @doc false
  def parse_controls(out) do
    for line <- String.split(out, "\n"),
        [_, name, type, rest] <- [Regex.run(~r/^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.*)$/, line)],
        into: %{} do
      nums = for [_, k, v] <- Regex.scan(~r/(min|max|step|default|value)=(-?\d+)/, rest), into: %{}, do: {String.to_atom(k), String.to_integer(v)}
      {name, Map.merge(%{type: type, inactive: String.contains?(rest, "inactive")}, nums)}
    end
  end

  @doc """
  Exposure (milliseconds) and gain, as far as this camera allows: manual
  exposure first, then the length clamped to the camera's range (UVC counts
  in units of 100 µs), then gain. Returns what was set.

  And the camera's own image processing off, where it lets it be
  (`processing: :camera` leaves it alone): sharpening draws a ring round
  every star, backlight compensation brightens a dark sky, and automatic
  white balance changes the picture's gray from one frame to the next. (A
  webcam-style camera like the SV105C also corrects its lens's vignetting
  and smooths its noise, with no control to stop it; `Image.stats/1` copes.)
  """
  def set(path, opts) do
    ctrls = controls(path)
    exe = System.find_executable("v4l2-ctl")

    cond do
      exe == nil or ctrls == %{} ->
        {:ok, %{}}

      true ->
        auto = Enum.find(["auto_exposure", "exposure_auto"], &Map.has_key?(ctrls, &1))
        length = Enum.find(["exposure_time_absolute", "exposure_absolute"], &Map.has_key?(ctrls, &1))

        wanted =
          [
            auto && {auto, 1},
            length && opts[:exposure_ms] && {length, clamp(round(opts[:exposure_ms] * 10), ctrls[length])},
            Map.has_key?(ctrls, "gain") && opts[:gain] && {"gain", clamp(opts[:gain], ctrls["gain"])}
          ]
          |> Kernel.++(if Keyword.get(opts, :processing, :off) == :off, do: processing_off(ctrls), else: [])
          |> Enum.reject(&(&1 in [nil, false]))

        # manual mode has to be in force before the length is accepted
        Enum.each(wanted, fn {k, v} -> System.cmd(exe, ["-d", path, "-c", "#{k}=#{v}"], stderr_to_stdout: true) end)
        {:ok, Map.new(wanted)}
    end
  end

  defp processing_off(ctrls) do
    for {k, v} <- [{"sharpness", :min}, {"backlight_compensation", :min}, {"white_balance_automatic", 0}],
        c = ctrls[k],
        c != nil,
        do: {k, if(v == :min, do: Map.get(c, :min, 0), else: v)}
  end

  defp clamp(v, %{min: lo, max: hi}), do: v |> max(lo) |> min(hi)
  defp clamp(v, _), do: v

  @doc "The longest exposure the camera allows, in milliseconds, or nil when it doesn't say."
  def max_exposure_ms(path) do
    ctrls = controls(path)

    case Enum.find(["exposure_time_absolute", "exposure_absolute"], &Map.has_key?(ctrls, &1)) do
      nil -> nil
      k -> ctrls[k][:max] && ctrls[k][:max] / 10
    end
  end

  # -- modes --------------------------------------------------------------------------------

  # what v4l2 calls a pixel format, and what ffmpeg calls it; raw first
  @raw %{"GREY" => "gray", "YUYV" => "yuyv422", "NV12" => "nv12", "YU12" => "yuv420p"}
  @compressed %{"MJPG" => "mjpeg"}

  @doc """
  The sizes and pixel formats the camera offers, from `v4l2-ctl
  --list-formats-ext`: `[%{format: "yuyv422", size: {1920, 1080}}]`, in
  ffmpeg's names. Empty where there's no v4l2-ctl (a Mac).
  """
  def modes(path) do
    with exe when is_binary(exe) <- System.find_executable("v4l2-ctl"),
         {out, 0} <- System.cmd(exe, ["-d", path, "--list-formats-ext"], stderr_to_stdout: true) do
      parse_modes(out)
    else
      _ -> []
    end
  end

  @doc false
  def parse_modes(out) do
    out
    |> String.split("\n")
    |> Enum.reduce({nil, []}, &mode_line/2)
    |> elem(1)
    |> Enum.reverse()
    |> Enum.uniq()
  end

  # a "[0]: 'YUYV'" line starts a format (nil when ffmpeg can't use it); the
  # "Size:" lines under it are its sizes (a range counts as its largest), and
  # the "Interval:" lines under a size its frame rates, of which the slowest
  # is kept (a long exposure needs a long frame)
  defp mode_line(line, {fmt, acc}) do
    format = Regex.run(~r/^\s*\[\d+\]:\s*'(.{4})'/, line)
    size = Regex.run(~r/Size:\s*\w+\s+(?:\d+x\d+\s*-\s*)?(\d+)x(\d+)/, line)
    interval = Regex.run(~r/Interval:\s*\w+\s+([\d.]+)s(?:\s*-\s*([\d.]+)s)?/, line)

    case {format, size, interval, acc} do
      {[_, fourcc], _, _, _} ->
        fourcc = String.trim_trailing(fourcc)
        {@raw[fourcc] || @compressed[fourcc], acc}

      {nil, [_, w, h], _, _} when fmt != nil ->
        {fmt, [%{format: fmt, size: {String.to_integer(w), String.to_integer(h)}} | acc]}

      {nil, nil, [_ | secs], [%{format: ^fmt} = mode | rest]} when fmt != nil ->
        {slowest, _} = secs |> List.last() |> Float.parse()
        fps = if slowest > 0, do: Float.round(1 / slowest, 3), else: nil
        {fmt, [Map.update(mode, :fps, fps, &min(&1, fps)) | rest]}

      _ ->
        {fmt, acc}
    end
  end

  @doc """
  The mode to take pictures in: the most pixels the camera has (the whole
  sensor, so the field of view the solver is told about is the real one),
  raw rather than JPEG at that size (JPEG smooths faint stars away). Nil
  when the camera doesn't say, and it gets its own default.
  """
  def best_mode([]), do: nil

  def best_mode(modes) do
    Enum.max_by(modes, fn %{format: f, size: {w, h}} -> {w * h, f in Map.values(@raw)} end)
  end

  # -- reading it --------------------------------------------------------------------------

  @doc """
  ffmpeg's input arguments for camera `path` in `mode` (from `best_mode/1`;
  the camera's own default when nil): v4l2 on Linux with the pixel format,
  size and slowest frame rate asked for, avfoundation on a Mac.
  """
  def input_args(path, mode), do: input(path, mode)

  defp input(path, mode) do
    case :os.type() do
      {:unix, :darwin} ->
        ["-f", "avfoundation", "-framerate", "30", "-i", "#{path}:none"]

      _ ->
        m = if mode, do: ["-input_format", mode.format, "-video_size", "#{elem(mode.size, 0)}x#{elem(mode.size, 1)}"], else: []
        m = if mode[:fps], do: m ++ ["-framerate", to_string(mode.fps)], else: m
        ["-f", "v4l2"] ++ m ++ ["-i", path]
    end
  end
end
