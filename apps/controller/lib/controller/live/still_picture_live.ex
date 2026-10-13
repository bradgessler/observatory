defmodule Controller.StillPictureLive do
  @moduledoc """
  One picture from the stills camera, and everything known about it
  (`/cameras/stills/pictures/:seq`).

  The page exists from the moment the picture has a number, before the
  shutter opens, and fills in as the picture goes through the box: the
  exposure, the camera finishing it, its files coming down and being saved,
  the stars measured in it, its plate solve, and its files leaving the box
  for the machine that collects them. Under that, what was recorded with it:
  the camera's settings, where the telescope pointed, the mount at shutter
  open and close, the alignment in force, the optics, the site, the box, and
  each file with its size and hash.

  Tapping a picture in the roll on Telescope Camera comes here (13 October
  2026: "take us to a page for that picture... the progression of metadata
  that is being added to this image").

  Read from the files the box wrote (`Controller.StillCamera.Record`), on
  the machine the camera is plugged into; the picture in flight comes from
  the camera's own news (`StillCamera.status().shot`).
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Machine, Settings, StillCamera}
  alias Controller.Components.Pictures
  alias Controller.StillCamera.Record

  @impl true
  def mount(%{"seq" => seq}, _session, socket) do
    seq =
      case Integer.parse(seq) do
        {n, ""} when n > 0 -> n
        _ -> nil
      end

    if connected?(socket) do
      StillCamera.subscribe()
      Settings.subscribe()
      Process.send_after(self(), :tick, 1_000)
    end

    cam = StillCamera.find()

    {:ok,
     socket
     |> assign(page_title: "Picture #{seq}", night: Settings.get("night", false), seq: seq, cam: cam, now_ms: System.system_time(:millisecond), ticks: 0)
     |> assign(pic: record(cam, seq))}
  end

  @impl true
  def handle_info({:still_camera, cam}, socket) do
    cam = StillCamera.prefer(socket.assigns.cam, cam)
    was = socket.assigns.cam
    socket = assign(socket, cam: cam)
    # the picture's own news: its stage changed, or it has just been finished. Read what was written.
    if stage_of(cam, socket.assigns.seq) != stage_of(was, socket.assigns.seq) or last_seq(cam) != last_seq(was),
      do: {:noreply, assign(socket, pic: record(cam, socket.assigns.seq) || socket.assigns.pic)},
      else: {:noreply, socket}
  end

  # A clock for the ages, and a look at the files every few seconds while something is still to
  # come (the solve's answer, the files being collected): those arrive without any news of their own.
  def handle_info(:tick, socket) do
    Process.send_after(self(), :tick, 1_000)
    ticks = socket.assigns.ticks + 1
    socket = assign(socket, now_ms: System.system_time(:millisecond), ticks: ticks)

    if rem(ticks, 3) == 0 and unfinished?(socket.assigns.pic),
      do: {:noreply, assign(socket, pic: record(socket.assigns.cam, socket.assigns.seq) || socket.assigns.pic)},
      else: {:noreply, socket}
  end

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info(_, socket), do: {:noreply, socket}

  # the record, from the machine the camera is on
  defp record(_cam, nil), do: nil

  defp record(cam, seq) do
    if StillCamera.remote?(cam),
      do: Machine.ask(cam.node, Record, :read, [seq], nil),
      else: Record.read(seq)
  catch
    _, _ -> nil
  end

  defp stage_of(%{shot: %{seq: seq} = shot}, seq), do: shot[:stage]
  defp stage_of(_, _), do: nil
  defp last_seq(%{last: %{seq: seq}}), do: seq
  defp last_seq(_), do: nil

  # still to come: the record itself, a solve that was asked for and has no answer, files not yet collected
  defp unfinished?(nil), do: true
  defp unfinished?(pic), do: solve_state(pic) in [:waiting] or Enum.any?(pic.files, & &1.here)

  # -- the page --------------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, steps: steps(assigns.cam, assigns.pic, assigns.seq), flight: flight(assigns.cam, assigns.seq))

    ~H"""
    <.page id="still-picture" night={@night}>
      <:header>
        <.back navigate={~p"/cameras/stills"} label="Telescope Camera" />
        <.title>Picture {@seq}</.title>
        <.actions><.stop /></.actions>
      </:header>

      <.split>
        <:main>
          <section class="scope-frame" aria-label={"picture #{@seq}"}>
            <img :if={shown?(@cam, @pic, @seq)} src={StillCamera.src_of(@cam, @seq)} alt={"Picture #{@seq}"} />
            <div :if={!shown?(@cam, @pic, @seq)} class="scope-frame-empty"><p class="dim">{empty_words(@pic, @flight)}</p></div>
            <p class="dim pic-caption">{caption(@pic, @flight, @now_ms)}</p>
          </section>

          <%!-- what has happened to it, in order: each step done, under way, or still to come --%>
          <section class="now-part" aria-labelledby="pic-steps-h">
            <h2 id="pic-steps-h" class="now-h">Through the box</h2>
            <ol class="pic-steps">
              <li :for={s <- @steps} class={"is-#{s.state}"} aria-current={s.state == :now && "step"}>
                <span class="pic-mark" aria-hidden="true">{mark(s.state)}</span>
                <span class="pic-step">
                  <strong>{s.label}</strong>
                  <small :if={s[:detail]}>{s.detail}</small>
                </span>
                <span class="pic-when">{s[:at] && clock(s.at)}<span class="sr-only">{state_words(s.state)}</span></span>
              </li>
            </ol>
            <p :if={@pic == nil && @flight == nil} class="dim" role="status">Nothing has been written for picture {@seq}. It may not have been taken yet, or it failed before its files were saved.</p>
          </section>
        </:main>

        <:side>
          <section :for={{title, rows} <- sections(@pic)} class="now-part" aria-label={title}>
            <h2 class="now-h">{title}</h2>
            <dl class="pic-facts">
              <div :for={{k, v} <- rows}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            </dl>
          </section>
          <p :if={@pic == nil} class="dim">What was recorded with the picture shows here once its files are saved: the camera's settings, where the telescope pointed, the mount, the alignment, the site.</p>
        </:side>
      </.split>
    </.page>
    """
  end

  defp mark(:done), do: "✓"
  defp mark(:now), do: "●"
  defp mark(:failed), do: "×"
  defp mark(:skipped), do: "–"
  defp mark(_), do: "○"

  defp state_words(:done), do: " (done)"
  defp state_words(:now), do: " (under way)"
  defp state_words(:failed), do: " (did not work)"
  defp state_words(:skipped), do: " (not asked for)"
  defp state_words(_), do: " (still to come)"

  # the picture can be drawn when the roll still has its grey copy
  defp shown?(cam, pic, seq), do: pic != nil and (Enum.any?(cam[:recent] || [], &(&1.seq == seq)) or last_seq(cam) == seq)

  defp empty_words(nil, %{} = flight), do: Pictures.shot_words(flight)
  defp empty_words(nil, _), do: "No picture"
  defp empty_words(_, _), do: "This picture has left the roll of the last few. Its files are listed here."

  defp caption(nil, %{} = flight, _now), do: Pictures.shot_words(flight)
  defp caption(nil, _, _), do: ""

  defp caption(pic, _, now) do
    c = pic.sidecar["camera"] || %{}
    at = time(pic.sidecar, "shutter_pressed")
    ["Taken #{if at, do: Pictures.age_words(%{at: at}, now), else: "at an unknown time"}", exposure_words(c), pic.name] |> Enum.reject(&(&1 in [nil, ""])) |> Enum.join(" · ")
  end

  # the picture in flight, when it is this one
  defp flight(%{shot: %{seq: seq} = shot}, seq), do: shot
  defp flight(_, _), do: nil

  # -- the steps -------------------------------------------------------------------------------

  @order [:preparing, :exposing, :processing, :downloading, :saving, :measuring]

  # Six steps, the same for every picture. Before the sidecar exists they come from the camera's
  # live stage; after it, from what was written.
  defp steps(cam, nil, seq) do
    case flight(cam, seq) do
      nil ->
        []

      shot ->
        at = Enum.find_index(@order, &(&1 == shot[:stage])) || 0
        st = fn stages -> flight_state(stages, at) end

        [
          %{state: st.([:preparing, :exposing]), label: "Exposure", detail: exposing_words(shot, cam)},
          %{state: st.([:processing]), label: "The camera finishes the picture", detail: nil},
          %{state: st.([:downloading, :saving]), label: "Files saved on the box", detail: shot[:stage] == :downloading && shot[:name]},
          %{state: st.([:measuring]), label: "Stars measured", detail: nil},
          %{state: :waiting, label: "Plate solve", detail: if(cam[:solving], do: nil, else: "Not asked for: plate solving is off")},
          %{state: :waiting, label: "Collected from the box", detail: nil}
        ]
    end
  end

  defp steps(_cam, pic, _seq) do
    s = pic.sidecar
    c = s["camera"] || %{}
    m = s["measured"]

    [
      %{state: :done, label: "Exposure", detail: exposure_words(c), at: time(s, "shutter_pressed")},
      %{state: :done, label: "The camera finished the picture", detail: took(time(s, "exposure_end"), time(s, "picture_ready")), at: time(s, "picture_ready")},
      %{state: :done, label: "Files saved on the box", detail: files_words(pic.files), at: time(s, "saved")},
      if(is_map(m), do: %{state: :done, label: "Stars measured", detail: measured_words(m, s)}, else: %{state: :skipped, label: "Stars measured", detail: "Nothing was measured in this picture"}),
      solve_step(pic),
      collected_step(pic)
    ]
  end

  defp flight_state(stages, at) do
    idx = Enum.map(stages, fn s -> Enum.find_index(@order, &(&1 == s)) end)

    cond do
      at in idx -> :now
      at > Enum.max(idx) -> :done
      true -> :waiting
    end
  end

  defp exposing_words(shot, cam) do
    settings = (cam[:camera] && cam.camera[:settings]) || %{}
    [shot[:stage] == :preparing && "Preparing the camera", settings[:shutter] && "#{settings.shutter} s", settings[:iso] && "ISO #{settings.iso}"] |> Enum.filter(&is_binary/1) |> Enum.join(" · ")
  end

  defp exposure_words(c) do
    [c["shutter"] && "#{c["shutter"]} s", c["iso"] && "ISO #{c["iso"]}", c["quality"]] |> Enum.filter(&is_binary/1) |> Enum.join(" · ")
  end

  defp files_words(files) do
    total = files |> Enum.map(&(&1.bytes || 0)) |> Enum.sum()
    "#{length(files)} #{if length(files) == 1, do: "file", else: "files"}, #{mb(total)}"
  end

  defp measured_words(m, s) do
    size = get_in(m, ["star_size", "arcsec"])

    [
      is_integer(m["stars"]) && "#{m["stars"]} #{if m["stars"] == 1, do: "star", else: "stars"}",
      is_number(size) && "star size #{Float.round(size / 1, 1)} arcsec",
      is_number(m["background"]) && "background #{m["background"]} of 255",
      is_number(s["transparency"]) && "transparency #{round(s["transparency"] * 100)}%"
    ]
    |> Enum.filter(&is_binary/1)
    |> Enum.join(" · ")
  end

  defp solve_state(%{sidecar: %{"plate_solve" => %{"queued" => true}}, solve: nil}), do: :waiting
  defp solve_state(%{solve: %{"state" => "solved"}}), do: :done
  defp solve_state(%{solve: %{}}), do: :failed
  defp solve_state(_), do: :skipped

  defp solve_step(pic) do
    case solve_state(pic) do
      :waiting ->
        %{state: :now, label: "Plate solve", detail: "Waiting for the solver's answer"}

      :done ->
        sol = pic.solve["solution"] || %{}

        detail =
          [
            is_number(sol["seconds"]) && "Solved in #{Float.round(sol["seconds"] / 1, 1)} s",
            is_integer(sol["stars"]) && "#{sol["stars"]} stars",
            is_number(sol["ra_deg"]) && is_number(sol["dec_deg"]) && "centre #{ra_words(sol["ra_deg"])} #{dec_words(sol["dec_deg"])}"
          ]
          |> Enum.filter(&is_binary/1)
          |> Enum.join(" · ")

        %{state: :done, label: "Plate solve", detail: detail, at: iso(pic.solve["written"])}

      :failed ->
        %{state: :failed, label: "Plate solve", detail: "No match: " <> Pictures.why_words(to_string(pic.solve["reason"] || pic.solve["state"])), at: iso(pic.solve["written"])}

      :skipped ->
        %{state: :skipped, label: "Plate solve", detail: "Not asked for: plate solving was off"}
    end
  end

  # the files are moved, never just deleted: gone from this card means a checked copy is elsewhere
  defp collected_step(pic) do
    here = Enum.count(pic.files, & &1.here)

    cond do
      pic.files == [] -> %{state: :skipped, label: "Collected from the box", detail: "No files were kept"}
      here == 0 -> %{state: :done, label: "Collected from the box", detail: "Its files have been copied off, checked against their hashes, and removed from this card"}
      here < length(pic.files) -> %{state: :now, label: "Collected from the box", detail: "#{length(pic.files) - here} of #{length(pic.files)} files collected"}
      true -> %{state: :waiting, label: "Collected from the box", detail: "On the box's card, waiting to be collected"}
    end
  end

  # -- what was recorded with it ---------------------------------------------------------------

  defp sections(nil), do: []

  defp sections(pic) do
    s = pic.sidecar

    [
      {"Camera", camera_rows(s["camera"])},
      {"Pointing", pointing_rows(s["pointing"], pic.solve)},
      {"Mount", mount_rows(s["mount"], s["settle"])},
      {"Alignment", model_rows(s["model"])},
      {"Telescope", optics_rows(s["optics"], pic.solve)},
      {"Site and clock", site_rows(s["site"], s["time"])},
      {"Box", box_rows(s["box"], pic)},
      {"Files", for(f <- pic.files, do: {f.name, "#{mb(f.bytes)} · #{if f.here, do: "on the box", else: "collected"} · sha256 #{String.slice(f.sha256 || "", 0, 12)}"})}
    ]
    |> Enum.map(fn {t, rows} -> {t, Enum.reject(rows, fn {_, v} -> v in [nil, ""] end)} end)
    |> Enum.reject(fn {_, rows} -> rows == [] end)
  end

  defp camera_rows(nil), do: []

  defp camera_rows(c) do
    [
      {"Model", [c["manufacturer"], c["model"]] |> Enum.filter(&is_binary/1) |> Enum.join(" ")},
      {"ISO", c["iso"] && to_string(c["iso"])},
      {"Shutter speed", c["shutter"] && "#{c["shutter"]} s"},
      {"Format", c["quality"]},
      {"Focus", c["focus"]},
      {"Battery", c["battery_pct"] && "#{c["battery_pct"]}%"}
    ]
  end

  defp pointing_rows(nil, _), do: []

  defp pointing_rows(p, solve) do
    sol = (solve && solve["solution"]) || %{}

    [
      {"By the mount", is_number(p["ra_deg"]) && is_number(p["dec_deg"]) && "#{ra_words(p["ra_deg"])} #{dec_words(p["dec_deg"])}"},
      {"From", p["source"]},
      {"By the plate solve", is_number(sol["ra_deg"]) && is_number(sol["dec_deg"]) && "#{ra_words(sol["ra_deg"])} #{dec_words(sol["dec_deg"])}"},
      {"Altitude and azimuth", is_number(p["alt_deg"]) && is_number(p["az_deg"]) && "#{round(p["alt_deg"])}° up, azimuth #{round(p["az_deg"])}°"},
      {"Field", is_number(sol["width_deg"]) && is_number(sol["height_deg"]) && "#{Float.round(sol["width_deg"] * 60, 1)} x #{Float.round(sol["height_deg"] * 60, 1)} arcmin, turned #{round(sol["rotation_deg"] || 0)}°"}
    ]
  end

  defp mount_rows(nil, _), do: []

  defp mount_rows(m, settle) do
    [
      {"Mount", m["id"]},
      {"At shutter open", axes(m["start"])},
      {"At shutter close", axes(m["end"])},
      {"Moved during the exposure", drift(m["start"], m["end"])},
      {"Since the last slew", is_map(settle) && is_number(settle["since_slew_s"]) && "#{round(settle["since_slew_s"])} s"}
    ]
  end

  defp axes(%{"ra" => %{"deg" => ra}, "dec" => %{"deg" => dec}}) when is_number(ra) and is_number(dec), do: "RA axis #{Float.round(ra / 1, 3)}° · Dec axis #{Float.round(dec / 1, 3)}°"
  defp axes(_), do: nil

  # how far each axis turned between shutter open and close, in arcseconds: tracking shows as the RA axis's steady turn
  defp drift(%{"ra" => %{"deg" => r1}, "dec" => %{"deg" => d1}}, %{"ra" => %{"deg" => r2}, "dec" => %{"deg" => d2}}) when is_number(r1) and is_number(r2) and is_number(d1) and is_number(d2),
    do: "RA axis #{round((r2 - r1) * 3600)} arcsec · Dec axis #{round((d2 - d1) * 3600)} arcsec"

  defp drift(_, _), do: nil

  defp model_rows(nil), do: []

  defp model_rows(m) do
    [
      {"Points", m["n"] && to_string(m["n"])},
      {"Fit", is_number(m["rms_arcmin"]) && "#{Float.round(m["rms_arcmin"] / 1, 1)} arcmin"},
      {"Polar axis", m["axis_words"]}
    ]
  end

  defp optics_rows(nil, _), do: []

  defp optics_rows(o, solve) do
    [
      {"Aperture", o["aperture_mm"] && "#{o["aperture_mm"]} mm"},
      {"Focal length", is_number(o["focal_length_mm"]) && "#{Float.round(o["focal_length_mm"] / 1, 1)} mm (from #{o["focal_length_from"] || "the label"})"},
      {"By this picture's solve", solve && is_number(solve["focal_length_mm"]) && "#{Float.round(solve["focal_length_mm"] / 1, 1)} mm"}
    ]
  end

  defp site_rows(site, time) do
    [
      {"Latitude and longitude", is_map(site) && is_number(site["lat"]) && is_number(site["lon"]) && "#{site["lat"]}, #{site["lon"]}"},
      {"Clock", is_map(time) && time["clock"]},
      {"Shutter pressed", is_map(time) && time["shutter_pressed"]}
    ]
  end

  defp box_rows(box, pic) do
    [
      {"Machine", is_map(box) && box["node"]},
      {"Firmware", is_map(box) && is_binary(box["firmware"]) && String.slice(box["firmware"], 0, 8)},
      {"Night", pic.night},
      {"Name", pic.name}
    ]
  end

  # -- small things ----------------------------------------------------------------------------

  defp time(sidecar, key), do: iso(get_in(sidecar, ["time", key]))

  defp iso(str) when is_binary(str) do
    case DateTime.from_iso8601(str) do
      {:ok, dt, _} -> dt
      _ -> nil
    end
  end

  defp iso(_), do: nil

  defp clock(%DateTime{} = dt), do: Calendar.strftime(dt, "%H:%M:%S") <> " UTC"

  defp took(%DateTime{} = a, %DateTime{} = b), do: "#{max(DateTime.diff(b, a), 0)} s after the shutter closed"
  defp took(_, _), do: nil

  # 63.57 degrees -> "04h 14m 17s"; -12.74 -> "−12° 44′"
  defp ra_words(deg) do
    s = round(deg / 15 * 3600)
    s = Integer.mod(s, 86_400)
    "#{pad(div(s, 3600))}h #{pad(div(rem(s, 3600), 60))}m #{pad(rem(s, 60))}s"
  end

  defp dec_words(deg) do
    m = round(abs(deg) * 60)
    "#{if deg < 0, do: "−", else: "+"}#{pad(div(m, 60))}° #{pad(rem(m, 60))}′"
  end

  defp pad(n), do: n |> Integer.to_string() |> String.pad_leading(2, "0")

  defp mb(nil), do: "size unknown"
  defp mb(bytes) when bytes >= 1_000_000, do: "#{Float.round(bytes / 1_000_000, 1)} MB"
  defp mb(bytes), do: "#{div(bytes, 1000)} kB"
end
