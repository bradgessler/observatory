defmodule Controller.Frames do
  @moduledoc """
  The telescope camera's frames, kept: written to the box's SD card, copied
  to the Mac, measured there. Each step is a queue with its own numbers
  (`Queues`), so the slow one shows on the Queues page.

      camera ─▶ frames.write ─▶ frames (spool, box's card) ─▶ frames.fetch (Mac) ─▶ frames.measure (Mac)

  **On the box** `frames.write` puts each frame the camera keeps
  (`Controller.ScopeCamera.keep/1`) into the `frames` spool: a file on the
  card, within the spool's budget and free-space floor (`Queues.Spool`). A
  slow card shows up as this step being busy.

  **On the Mac** (any machine with `config :controller, :frames, pull:
  true`) `Controller.Frames.Pull` leases frames from every spool on the
  cluster whenever `frames.fetch` has room. `frames.fetch` copies each one
  over HTTP (the cluster's connection carries only the lease and the ack,
  never the bytes), straight from disk when the spool is on the same
  machine; checks its SHA-256; acks it, so the box may delete it when it
  needs the room; and hands it to `frames.measure`, which finds its stars.

  Frames are FITS files (`Controller.Fits`), everything known about each in
  its own header (`Controller.ScopeCamera.Header`): when, the camera and
  its controls, the mount at the start and end, the model, the site, what
  the box measured. The copy and the measuring here add to the same header.
  They land in `~/.observatory/frames/<date>/<id>.fits`.
  """

  alias Controller.{Fits, Repo}
  alias Controller.Frames.Frame
  alias Controller.ScopeCamera.{Header, Image}
  alias Queues.Spool

  @spool "frames"

  @doc "Where this machine keeps the frames it has copied."
  def dir, do: config(:dir, Path.join([System.user_home!(), ".observatory", "frames"]))

  @doc "Where the box's spool keeps frames waiting to be copied."
  def spool_dir, do: config(:spool_dir, Path.join([System.user_home!(), ".observatory", "spool", @spool]))

  @doc """
  Is this machine copying frames from the boxes right now? A saved setting
  (`"frames_copy"`, on by default): paused, frames wait on each box's card
  within its limits, and the box's Wi-Fi is left to the phones using it (a
  Pi 3's radio carries about 2 MB/s, and a frame a second is a quarter of it).
  """
  def copying?, do: Controller.Settings.get("frames_copy", true) != false

  @doc "Copy frames from the boxes (true), or pause (false). Saved, and every page sees it."
  def copying(on?) when is_boolean(on?), do: Controller.Settings.put("frames_copy", on?)

  @doc "How many frames the card keeps, newest first: the setting `\"frames_keep_last\"` (1000), or `:infinity` for \"all\"."
  def keep_last do
    case Controller.Settings.get("frames_keep_last", 1000) do
      n when is_integer(n) and n > 0 -> n
      _ -> :infinity
    end
  end

  @doc "Does this machine copy frames from the boxes (the Mac)?"
  def pull?, do: config(:pull, false)

  @doc """
  Keep one frame (`%{pgm, record, context}`: the picture, what the camera
  made of it, and the moment it was taken): queued for the card at once, or
  `{:error, :full}` when the card can't keep up and it's dropped (counted on
  the Queues page). Never waits.
  """
  def keep(%{pgm: pgm} = frame) do
    id = Spool.new_id()
    item = %{id: id, pgm: pgm, record: Map.get(frame, :record, %{}), context: Map.get(frame, :context, %{})}
    Queues.push("frames.write", item, bytes: byte_size(pgm))
  end

  # -- the steps -------------------------------------------------------------------------------

  @doc false
  # frames.write: a FITS file, everything known in its header, onto the card
  def write(%{id: id, pgm: pgm, record: record, context: context}) do
    with {:ok, img} <- Image.from_pgm(pgm) do
      cards = Header.cards(Map.merge(%{at: DateTime.utc_now()}, record), context)
      Spool.put(@spool, id <> ".fits", Fits.encode(img, cards), %{seq: record[:seq], record: record})
    end
  end

  @doc false
  # frames.fetch: one leased frame from `node`'s spool to this machine, checked, then acked
  def fetch(%{node: node, id: id} = lease) do
    dest = Path.join([dir(), date(id), id])
    File.mkdir_p!(Path.dirname(dest))
    part = dest <> ".part"
    t = fn fun -> {us, r} = :timer.tc(fun); {r, div(us, 1000)} end

    result =
      with {:ok, download} <- timed(t, fn -> copy(lease, part) end),
           {:ok, check} <- timed(t, fn -> check(part, lease.sha256) end) do
        {_, save} =
          t.(fn ->
            File.rename!(part, dest)
            # where this copy came from, in the file itself
            stamp(dest, [
              {"OBS COPY FROM", to_string(node), "the box whose card it waited on"},
              {"OBS COPY TO", to_string(node()), "this machine"},
              {"OBS COPY AT", DateTime.utc_now(), "UTC"},
              {"OBS COPY DOWNLOAD MS", download},
              # a 64-character checksum doesn't fit one HIERARCH line: in two halves
              {"OBS COPY SHA256 A", String.slice(lease.sha256 || "", 0, 32), "SHA-256 as it left the box, first half"},
              {"OBS COPY SHA256 B", String.slice(lease.sha256 || "", 32, 32), "second half"}
            ])
          end)

        {_, index} = t.(fn -> record_copy(dest, id, lease) end)
        {_, ack} = t.(fn -> remote(node, Spool, :ack, [@spool, id]) end)
        # measuring is the next step's business: if it's full, the frame is kept unmeasured
        Queues.push("frames.measure", %{path: dest}, bytes: lease.bytes)
        {:ok, dest, %{"download" => download, "check" => check, "save" => save, "index" => index, "ack to the box" => ack}}
      end

    with {:error, _} <- result do
      File.rm(part)
      remote(node, Spool, :release, [@spool, id])
    end

    result
  end

  defp timed(t, fun) do
    case t.(fun) do
      {:ok, ms} -> {:ok, ms}
      {err, _} -> err
    end
  end

  @doc false
  # frames.measure: the stars in a copied frame, measured again here and written into its header
  def measure(%{path: path}) do
    with {:ok, f} <- Fits.read(File.read!(path)) do
      img = Map.take(f, [:w, :h, :px])
      stats = Image.stats(img)
      stars = Image.stars(img, stats: stats)
      focus = Image.focus(stars)
      verdict = Image.verdict(stats, stars)

      record_measure(path, focus, verdict)

      stamp(path, [
        {"OBS MEASURED ON", to_string(node()), "measured again after the copy"},
        {"OBS MEASURED BACKGROUND", stats.background},
        {"OBS MEASURED NOISE", Float.round(stats.noise * 1.0, 2)},
        {"OBS MEASURED STARS", focus.stars},
        {"OBS MEASURED HFR PX", focus.hfr && Float.round(focus.hfr * 1.0, 3)},
        {"OBS MEASURED VERDICT", verdict}
      ])

      {:ok, verdict}
    end
  end

  # -- the database --------------------------------------------------------------------------

  @doc """
  Frames copied to this machine, newest first: `[%Frame{}]`. Options:
  `limit:` (50), `since:` a DateTime, `with_stars:` true for only those with stars.
  Empty when the database isn't up.
  """
  def copied(opts \\ []) do
    if Repo.up?() do
      import Ecto.Query

      q = from f in Frame, where: f.place == "copied", order_by: [desc: f.taken_at, desc: f.id], limit: ^Keyword.get(opts, :limit, 50)
      q = if since = opts[:since], do: from(f in q, where: f.taken_at >= ^since), else: q
      q = if opts[:with_stars], do: from(f in q, where: f.stars > 0), else: q
      Repo.all(q)
    else
      []
    end
  end

  @doc "Frames waiting on this machine's card (the spool's index), oldest first."
  def on_card do
    if Repo.up?() do
      import Ecto.Query
      Repo.all(from f in Frame, where: f.place == "spool", order_by: [asc: f.id])
    else
      []
    end
  end

  # a copied frame, its header in a row: queryable from now on
  defp record_copy(dest, id, lease) do
    if Repo.up?() do
      # a frame that isn't FITS (from before the headers) is recorded without one
      header = with {:ok, h} <- Fits.read_header(dest), do: h, else: (_ -> [])

      attrs =
        Map.merge(Frame.from_header(header), %{place: "copied", id: id, state: "copied", path: dest, bytes: lease.bytes, sha256: lease.sha256})

      %Frame{} |> Frame.changeset(attrs) |> Repo.insert!(on_conflict: {:replace_all_except, [:inserted_at]}, conflict_target: [:place, :id])
    end

    :ok
  end

  defp record_measure(path, focus, verdict) do
    if Repo.up?() do
      import Ecto.Query

      from(f in Frame, where: f.place == "copied" and f.path == ^path)
      |> Repo.update_all(
        set: [state: "measured", measured_stars: focus.stars, measured_hfr_px: focus.hfr && focus.hfr / 1, measured_verdict: to_string(verdict), updated_at: DateTime.utc_now()]
      )
    end

    :ok
  end

  # cards into a FITS file's header; a frame that isn't FITS (an older one) is left as it is
  defp stamp(path, cards) do
    if String.ends_with?(path, ".fits"), do: Fits.update(path, cards), else: :ok
  end

  defp copy(%{node: node, path: path}, part) when node == node(), do: File.cp(path, part)

  defp copy(%{url: url}, part) when is_binary(url) do
    case Req.get(url, into: File.stream!(part), retry: false, receive_timeout: 120_000, decode_body: false) do
      {:ok, %{status: 200}} -> :ok
      {:ok, %{status: s}} -> {:error, {:http, s}}
      {:error, e} -> {:error, e}
    end
  end

  defp copy(_, _), do: {:error, :no_url}

  defp check(path, sha) do
    if Spool.sha256_file(path) == sha, do: :ok, else: {:error, :checksum}
  end

  # ids start with milliseconds since 1970: the frame's night, in UTC
  defp date(id) do
    case Integer.parse(id) do
      {ms, _} -> ms |> DateTime.from_unix!(:millisecond) |> DateTime.to_date() |> Date.to_iso8601()
      :error -> "undated"
    end
  end

  @doc false
  # a call to `node`, or here; never raises (a box that left mid-copy is an error, not a crash)
  def remote(node, m, f, a) when node == node(), do: apply(m, f, a)

  def remote(node, m, f, a) do
    :erpc.call(node, m, f, a, 10_000)
  catch
    kind, reason -> {:error, {:remote, kind, reason}}
  end

  @doc false
  def url(id), do: Controller.Endpoint.url() <> "/spool/#{@spool}/#{id}"

  defp config(key, default), do: Keyword.get(Application.get_env(:controller, :frames, []), key, default)
end
