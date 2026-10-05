defmodule Controller.Sky.Solve.Local do
  @moduledoc """
  Plate solving on this machine with astrometry.net and the Tycho-2 index
  files in `~/.observatory/astrometry` (see `priv/docs/align-photo.md`).

  One pipeline on the Mac and on the Pi, four C programs, no Python (the Pi
  has none, and solve-field only reaches for it to convert images and for
  two clean-up passes, all of which this avoids):

      djpeg -grayscale -pnm -outfile photo.pgm photo.jpg     # a JPEG from the phone
      an-pnmtofits -q -o photo.fits photo.pgm
      image2xy -O -d 2 -o photo.xy.fits photo.fits           # "simplexy: found N sources."
      solve-field --no-remove-lines --uniformize 0 --width W --height H \\
        --x-column X --y-column Y --sort-column FLUX [--ra --dec --radius] photo.xy.fits

  A phone held to an eyepiece gives a bright disc (moonlight, light
  pollution) with a hard rim, in a black frame. Raw, the star finder counts
  the rim and the background grain as thousands of stars and nothing solves;
  so (`clean:`, on by default) the photo is first
  cut to the eyepiece's field: the disc found from a blurred threshold,
  shrunk 50 px so the rim is gone, the moonlight taken off by subtracting a
  heavily blurred copy, and cropped. Of the first night's real eyepiece
  photos, the cleaned ones solved and the raw ones did not. The crop's
  centre is the eyepiece's centre, so the solved centre is the tube's
  optical axis. The steps run in Elixir (`Controller.Sky.Solve.Clean`), the
  same on the Mac and the Pi (which has no ImageMagick). On the first
  night's 15 photos that solves the 10 ImageMagick did, and one more, in a
  fraction of the time; `clean: :magick` still runs the ImageMagick version.

  The star count from image2xy decides early: fewer than `min_stars` and
  solve-field is not even started (with 8 to 12 stars it grinds to its CPU
  limit without a match). Each step runs in the solve's own temp directory
  through a runner (`Controller.Sky.Solve.Runner`) that enforces what is
  left of one deadline and kills the step and everything it started; the
  directory is removed afterwards.

      Local.solve(jpeg_bytes, hint: %{ra_deg: 86.0, dec_deg: -2.0, radius_deg: 10})
      #=> {:ok, %{ra_deg: 83.8199, dec_deg: -5.3900, width_deg: 1.0, height_deg: 1.0,
      #          rotation_deg: -142.99, parity: "neg", stars: 129, seconds: 0.4, ...}}

  Knobs (function options; the machine-wide ones also in
  `config :controller, :solver, [...]`, options winning):

    * `hint:` where the scope roughly points, `%{ra_deg, dec_deg, radius_deg}`
      or `{ra, dec, radius}`: a hinted solve is a fraction of a second, a
      blind one up to a minute
    * `blind_fallback:` (true) stars but no match near the hint: try once
      more without it, in whatever time is left
    * `scale:` `{low_deg, high_deg}` across the image, default `{0.2, 3.0}`
      (a phone at a low-power eyepiece)
    * `downsample:` an integer, or `:auto` from the image size: 2 for a
      12 MP phone photo, 4 above that
    * `nsigma:` image2xy's detection threshold in sigmas (its own default,
      which finds about what solve-field finds in a JPEG, when not given)
    * `min_stars:` (15) fewer sources than this is `:too_few_stars`
    * `clean:` (true) crop to the eyepiece field first, in Elixir; `:magick`
      with ImageMagick instead, when it is here; false never
    * `min_odds:` (1.0e18) how sure a match must be. solve-field's own
      default (1e9) let through two false matches the first night, each on
      3 stars at about 1e9; every real one scored 1e28 or better
    * `timeout:` milliseconds for the whole pipeline (90 000)
    * `solve_field:`, `djpeg:`, `an_pnmtofits:`, `image2xy:` executables
      (default: on PATH, else beside solve-field, else Homebrew's)
    * `index_config:` the astrometry.cfg (default `~/.observatory/astrometry/astrometry.cfg`)
    * `runner:` `{module, opts}` (default `{Controller.Sky.Solve.Runner.Port, []}`)
    * `tmp_dir:` where the per-solve directory goes

  Errors: `:too_few_stars`, `:no_solution` (stars, none that match),
  `:timeout`, `:no_solver` (a program or the index config is missing),
  `:unsupported_image` (JPEG, netpbm or FITS only for now), or
  `{step, exit_status, last_line}` when a program fails.
  """

  require Logger
  alias Controller.Sky.Photo
  alias Controller.Sky.Solve.Runner

  @default_timeout 90_000
  # Fewer sources than this and solve-field grinds to its CPU limit without a
  # match (eyepiece plates: 17 stars solved in 4 s, 12 never did).
  @min_stars 15
  # Fewer than this and a blind retry is not worth its minutes. It was 20 until
  # the night two telescope frames with 15 and 19 stars failed on a hint that
  # was 19 degrees wrong, then solved in 3 s once told where to look: a narrow
  # field has few stars, and the hint is as likely to be the trouble as they are.
  @min_stars_for_blind 10
  @bins ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
  @steps [:solve_field, :djpeg, :an_pnmtofits, :image2xy]
  # used when there, never required
  @optional [:magick]
  @min_odds 1.0e18

  # -- the machine ------------------------------------------------------------------------

  @doc "Can this machine solve? Every program and the index config are there."
  def available?(opts \\ []), do: Enum.all?(@steps, &executable(&1, opts)) and File.regular?(index_config(opts))

  @doc "The executable for a step (`:solve_field`, `:djpeg`, `:an_pnmtofits`, `:image2xy`), or nil."
  def executable(step, opts \\ []) when step in @steps or step in @optional do
    name = step |> Atom.to_string() |> String.replace("_", "-")

    case opt(opts, step) do
      nil ->
        beside = if step != :solve_field, do: (sf = executable(:solve_field, opts)) && Path.join(Path.dirname(sf), name)
        System.find_executable(name) || Enum.find([beside | Enum.map(@bins, &Path.join(&1, name))], &(&1 && File.regular?(&1)))

      path ->
        if File.regular?(path), do: path
    end
  end

  @doc "The astrometry.cfg this machine would use."
  def index_config(opts \\ []), do: opt(opts, :index_config) || Path.join([System.user_home!(), ".observatory", "astrometry", "astrometry.cfg"])

  @doc "A knob: the function option, else `config :controller, :solver, [...]`."
  def opt(opts, key) do
    case Keyword.fetch(opts, key) do
      {:ok, v} -> v
      :error -> Keyword.get(config(), key)
    end
  end

  defp config do
    case Application.get_env(:controller, :solver, []) do
      list when is_list(list) -> if Keyword.keyword?(list), do: list, else: []
      _ -> []
    end
  end

  defp runner(opts), do: opt(opts, :runner) || {Runner.Port, []}

  # -- the pipeline ---------------------------------------------------------------------

  @doc "Solve one image (its bytes). See the moduledoc for the knobs."
  def solve(image, opts \\ []) when is_binary(image) do
    started = System.monotonic_time(:millisecond)
    deadline = started + (opt(opts, :timeout) || @default_timeout)
    format = Photo.format(image)

    cond do
      not available?(opts) ->
        {:error, :no_solver}

      format not in [:jpeg, :pgm, :ppm, :fits] ->
        {:error, :unsupported_image}

      true ->
        dir = Path.join(opt(opts, :tmp_dir) || System.tmp_dir!(), "observatory-solve-#{System.unique_integer([:positive])}")
        File.mkdir_p!(dir)
        # a caller killed mid-solve never reaches `after`: this removes the directory then
        sweeper = sweeper(self(), dir)

        try do
          with {:ok, fits, dims} <- to_fits(image, format, dir, opts, deadline),
               {:ok, xy, stars} <- extract(fits, dims, dir, opts, deadline),
               {:ok, sol} <- match(xy, dims, stars, dir, opts, deadline) do
            {:ok, Map.merge(sol, %{stars: stars, seconds: (System.monotonic_time(:millisecond) - started) / 1000})}
          end
        after
          send(sweeper, :done)
          File.rm_rf(dir)
        end
    end
  end

  defp sweeper(owner, dir) do
    spawn(fn ->
      ref = Process.monitor(owner)

      receive do
        :done -> :ok
        # the runner's reaper is killing the programs at the same moment: give it a beat
        {:DOWN, ^ref, :process, _, _} -> Process.sleep(200) && File.rm_rf(dir)
      end
    end)
  end

  # the photo as a FITS image, and its size
  defp to_fits(image, :fits, dir, _opts, _deadline) do
    path = Path.join(dir, "photo.fits")
    File.write!(path, image)

    case Photo.dimensions(image) do
      {:ok, dims} -> {:ok, path, dims}
      _ -> {:error, :unsupported_image}
    end
  end

  defp to_fits(image, format, dir, opts, deadline) do
    pnm = Path.join(dir, "photo" <> Photo.extension(if format == :jpeg, do: :pgm, else: format))
    fits = Path.join(dir, "photo.fits")

    grey =
      if format == :jpeg do
        jpg = Path.join(dir, "photo.jpg")
        File.write!(jpg, image)

        plain = fn -> step(:djpeg, ["-grayscale", "-pnm", "-outfile", pnm, jpg], dir, opts, deadline) end

        case {opt(opts, :clean), executable(:magick, opts)} do
          {false, _} -> plain.()
          {:magick, magick} when magick != nil -> with {:ok, :no_eyepiece} <- clean(jpg, pnm, dir, opts, deadline), do: plain.()
          _ -> with {:ok, :no_eyepiece} <- clean_here(jpg, pnm, dir, opts, deadline), do: plain.()
        end
      else
        File.write!(pnm, image)
        {:ok, ""}
      end

    with {:ok, _} <- grey,
         {:ok, dims} <- pnm_dims(pnm),
         {:ok, _} <- step(:an_pnmtofits, ["-q", "-o", fits, pnm], dir, opts, deadline) do
      {:ok, fits, dims}
    end
  end

  # The eyepiece's field only, stars on black (see the moduledoc). No disc
  # found (a star field straight off a camera, or a photo of something else):
  # `{:ok, :no_eyepiece}`, and the photo goes the plain way.
  defp clean(jpg, pnm, dir, opts, deadline) do
    grey = Path.join(dir, "grey.png")
    mask = Path.join(dir, "mask.png")

    with {:ok, _} <- step(:magick, [jpg, "-auto-orient", "-colorspace", "Gray", "-depth", "16", grey], dir, opts, deadline),
         {:ok, _} <- step(:magick, [grey, "-blur", "0x10", "-threshold", "8%", "-morphology", "Erode", "Disk:50", mask], dir, opts, deadline),
         {:ok, disc} <- eyepiece(mask, dir, opts, deadline) do
      case disc do
        %{box: box} ->
          step(:magick,
            [grey, "(", "+clone", "-blur", "0x25", ")", "-compose", "Minus_Src", "-composite",
             mask, "-compose", "Multiply", "-composite", "-crop", box, "+repage", "-auto-level", "-depth", "8", pnm],
            dir, opts, deadline)

        nil ->
          # extraction goes back to its own defaults too (it keys off the mask)
          File.rm(mask)
          {:ok, :no_eyepiece}
      end
    end
  end

  # The same, in Elixir: the disc and the moonlight from djpeg's eighth-size
  # copy, the stars from the photo itself (the star finder halves it, as
  # after ImageMagick).
  defp clean_here(jpg, pnm, dir, opts, deadline) do
    small = Path.join(dir, "small.pgm")
    full = Path.join(dir, "full.pgm")

    with {:ok, _} <- step(:djpeg, ["-grayscale", "-scale", "1/8", "-pnm", "-outfile", small, jpg], dir, opts, deadline),
         {:ok, _} <- step(:djpeg, ["-grayscale", "-pnm", "-outfile", full, jpg], dir, opts, deadline) do
      case Controller.Sky.Solve.Clean.eyepiece(File.read!(small), File.read!(full), 8) do
        {:ok, cleaned, _info} ->
          File.write!(pnm, cleaned)
          File.write!(Path.join(dir, "cleaned"), "")
          {:ok, ""}

        _ ->
          {:ok, :no_eyepiece}
      end
    end
  end

  # Moonlight flaring off the eyepiece's edge survives the threshold as a
  # second bright blob, and a crop around both lets the glare in (the first
  # night, plate fifteen). The eyepiece is the biggest bright region: keep
  # only that, and crop to it.
  defp eyepiece(mask, dir, opts, deadline) do
    listing = ["-define", "connected-components:verbose=true", "-connected-components", "8", "null:"]

    with {:ok, out} <- step(:magick, [mask | listing], dir, opts, deadline) do
      case eyepiece_disc(out) do
        nil ->
          {:ok, nil}

        disc ->
          keep = ["-define", "connected-components:keep-ids=#{disc.id}", "-define", "connected-components:mean-color=true", "-connected-components", "8", "-threshold", "50%", mask]

          with {:ok, _} <- step(:magick, [mask | keep], dir, opts, deadline), do: {:ok, disc}
      end
    end
  end

  @min_disc 0.05

  @doc """
  The eyepiece in magick's connected-components listing of the mask
  (`"  4: 1212x1201+594+535 1201.7,1137.5 1.13597e+06 gray(255)"`): the
  biggest bright region, `%{id, box}`, or nil when there is none worth the
  name. A disc covers a good part of an eyepiece photo (a quarter, the first
  night); under #{round(@min_disc * 100)}% of the frame it is the halo of a
  bright star, not an eyepiece.
  """
  def eyepiece_disc(listing) do
    regions =
      for line <- String.split(listing, "\n"),
          [_, id, box, area, colour] <- [Regex.run(~r/^\s*(\d+):\s+(\d+x\d+\+\d+\+\d+)\s+\S+\s+(\S+)\s+(\S+)/, line)],
          {a, _} <- [Float.parse(area)],
          do: %{id: id, box: box, area: a, bright: colour in ["gray(255)", "white", "srgb(255,255,255)", "gray(65535)"]}

    frame = regions |> Enum.map(& &1.area) |> Enum.sum()

    case regions |> Enum.filter(& &1.bright) |> Enum.max_by(& &1.area, fn -> nil end) do
      %{area: a} = disc when a >= @min_disc * frame -> Map.take(disc, [:id, :box])
      _ -> nil
    end
  end

  defp pnm_dims(path) do
    head = File.open!(path, [:read, :binary], &IO.binread(&1, 512))

    case is_binary(head) && Photo.dimensions(head) do
      {:ok, dims} -> {:ok, dims}
      _ -> {:error, :unsupported_image}
    end
  end

  # the stars in it, as an xylist; too few and there is nothing to match
  defp extract(fits, dims, dir, opts, deadline) do
    xy = Path.join(dir, "photo.xy.fits")
    cleaned? = File.exists?(Path.join(dir, "cleaned")) or File.exists?(Path.join(dir, "mask.png"))
    # A cleaned eyepiece photo still carries JPEG grain, which image2xy's own
    # threshold counts by the hundred: the first night's photos solved on
    # confident stars only (40 sigma, at half size) and not on its default.
    nsigma = opt(opts, :nsigma) || if(cleaned?, do: 40)
    down =
      cond do
        opt(opts, :downsample) != nil -> downsample(opt(opts, :downsample), dims)
        cleaned? -> 2
        true -> downsample(:auto, dims)
      end

    args =
      ["-O"] ++
        if(nsigma, do: ["-p", num(nsigma)], else: []) ++
        if(down > 1, do: ["-d", Integer.to_string(down)], else: []) ++ ["-o", xy, fits]

    with {:ok, out} <- step(:image2xy, args, dir, opts, deadline) do
      n = stars(out) || 0
      if n < (opt(opts, :min_stars) || @min_stars), do: {:error, :too_few_stars}, else: {:ok, xy, n}
    end
  end

  # solve-field on the star list: hinted first, then blind if the hint may be what is wrong
  defp match(xy, dims, stars, dir, opts, deadline) do
    hint = hint(opts[:hint])

    case solve_field(xy, dims, dir, Keyword.put(opts, :hint, hint), deadline) do
      {:error, :no_solution} when hint != nil and stars >= @min_stars_for_blind ->
        if Keyword.get(opts, :blind_fallback, true) and deadline - System.monotonic_time(:millisecond) > 2_000,
          do: solve_field(xy, dims, dir, Keyword.put(opts, :hint, nil), deadline),
          else: {:error, :no_solution}

      other ->
        other
    end
  end

  defp solve_field(xy, dims, dir, opts, deadline) do
    left = deadline - System.monotonic_time(:millisecond)

    with {:ok, out} <- step(:solve_field, args(xy, dims, dir, Keyword.put(opts, :cpu_ms, left)), dir, opts, deadline) do
      parse(out)
    end
  end

  @doc "solve-field's arguments for a star list (public so a test can see exactly what is asked for)."
  def args(xy, {w, h}, dir, opts) do
    {low, high} = Keyword.get(opts, :scale, {0.2, 3.0})
    cpu_s = max(1, div(Keyword.get(opts, :cpu_ms, @default_timeout), 1000))

    hint =
      case opts[:hint] do
        %{ra_deg: ra, dec_deg: dec, radius_deg: r} -> ["--ra", num(ra), "--dec", num(dec), "--radius", num(r)]
        _ -> []
      end

    ["--config", index_config(opts), "--overwrite", "--no-plots", "--no-remove-lines", "--uniformize", "0",
     "--width", Integer.to_string(w), "--height", Integer.to_string(h),
     "--x-column", "X", "--y-column", "Y", "--sort-column", "FLUX",
     "--dir", dir, "--temp-dir", dir, "--out", "solve",
     "--scale-units", "degwidth", "--scale-low", num(low), "--scale-high", num(high), "--cpulimit", Integer.to_string(cpu_s),
     "--odds-to-solve", :erlang.float_to_binary((opt(opts, :min_odds) || @min_odds) / 1, [:short]),
     # only the WCS is needed (it is what prints the field centre)
     "--new-fits", "none", "--index-xyls", "none", "--rdls", "none", "--corr", "none", "--match", "none"] ++
      hint ++ [xy]
  end

  @doc "The downsample factor for an image: 2 for a phone photo, 4 for a huge one, 1 for small."
  def downsample(n, _dims) when is_integer(n) and n >= 1, do: n
  def downsample(_, {w, h}) when max(w, h) > 4_200, do: 4
  def downsample(_, {w, h}) when max(w, h) > 1_600, do: 2
  def downsample(_, _), do: 1

  defp hint(%{ra_deg: ra, dec_deg: dec} = h), do: %{ra_deg: ra / 1, dec_deg: dec / 1, radius_deg: (h[:radius_deg] || 15) / 1}
  defp hint({ra, dec, r}), do: %{ra_deg: ra / 1, dec_deg: dec / 1, radius_deg: r / 1}
  defp hint(_), do: nil

  # One program through the runner, with what is left of the deadline.
  # solve-field's "did not solve" is not a failure of the program: its words
  # are read by parse/1 whatever the exit status.
  defp step(name, args, dir, opts, deadline) do
    left = deadline - System.monotonic_time(:millisecond)
    exe = executable(name, opts)
    path = Enum.join([Path.dirname(exe) | @bins] ++ ["/bin", System.get_env("PATH", "")], ":")

    if left <= 0 do
      {:error, :timeout}
    else
      Logger.debug("#{name} #{Enum.join(args, " ")}")

      case Runner.run(runner(opts), exe, args, cd: dir, env: [{"PATH", path}, {"TMPDIR", dir}], timeout: left) do
        {:ok, 0, out} -> {:ok, out}
        {:ok, _status, out} when name == :solve_field -> {:ok, out}
        {:ok, status, out} -> {:error, {name, status, last_line(out)}}
        {:error, :timeout} -> {:error, :timeout}
        {:error, reason} -> {:error, {name, reason}}
      end
    end
  end

  defp last_line(out), do: out |> String.split("\n", trim: true) |> List.last() |> Kernel.||("") |> String.slice(0, 200)
  defp num(x) when is_integer(x), do: Integer.to_string(x)
  defp num(x), do: :erlang.float_to_binary(x / 1, decimals: 6)

  # -- reading solve-field -----------------------------------------------------------------

  @doc """
  Read solve-field's report. `{:ok, %{ra_deg, dec_deg, width_deg, height_deg,
  rotation_deg, parity, pixscale_arcsec, index}}` when it solved,
  `{:error, :no_solution}` when it did not.
  """
  def parse(out) when is_binary(out) do
    with [_, ra, dec] <- Regex.run(~r/Field center: \(RA,Dec\) = \(\s*([-\d.eE+]+),\s*([-\d.eE+]+)\s*\) deg\./, out),
         {ra, _} <- Float.parse(ra),
         {dec, _} <- Float.parse(dec) do
      {w, h} = field_size(out)

      {:ok,
       %{
         ra_deg: ra,
         dec_deg: dec,
         width_deg: w,
         height_deg: h,
         rotation_deg: float(~r/Field rotation angle: up is ([-\d.eE+]+) degrees E of N/, out),
         parity: capture(~r/Field parity: (\w+)/, out),
         pixscale_arcsec: float(~r/pixel scale ([-\d.eE+]+) arcsec\/pix/, out),
         index: capture(~r/solved with index (\S+?)\.fits/, out)
       }}
    else
      _ -> {:error, :no_solution}
    end
  end

  @doc "How many sources image2xy (or solve-field's own extraction) reported, or nil."
  def stars(out) do
    case Regex.scan(~r/simplexy: found (\d+) sources/, out) do
      [] -> nil
      found -> found |> List.last() |> List.last() |> String.to_integer()
    end
  end

  # "Field size: 59.9961 x 59.9985 arcminutes" (or degrees, or arcseconds)
  defp field_size(out) do
    case Regex.run(~r/Field size: ([\d.eE+]+) x ([\d.eE+]+) (degrees|arcminutes|arcseconds)/, out) do
      [_, w, h, unit] ->
        k = %{"degrees" => 1.0, "arcminutes" => 1 / 60, "arcseconds" => 1 / 3600}[unit]
        {elem(Float.parse(w), 0) * k, elem(Float.parse(h), 0) * k}

      _ ->
        {nil, nil}
    end
  end

  defp capture(re, out) do
    case Regex.run(re, out) do
      [_, x] -> x
      _ -> nil
    end
  end

  defp float(re, out) do
    case Regex.run(re, out) do
      [_, x] -> elem(Float.parse(x), 0)
      _ -> nil
    end
  end
end
