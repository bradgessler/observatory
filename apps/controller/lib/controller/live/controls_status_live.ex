defmodule Controller.ControlsStatusLive do
  @moduledoc """
  The Controls section's status, in the toolbar of every page that moves the
  mount: whether it's slewing, tracking or still (a lamp and the word), and
  where it points. Right ascension and declination once alignment (or home)
  says where the axes point on the sky; the axes' own angles until then,
  said as such.

  Its own small LiveView, nested in the page's header: it follows its mount
  (four reports a second) and redraws only itself, so a page needn't carry
  the mount's position to show it.

      {live_render(@socket, Controller.ControlsStatusLive, id: "controls-status", session: %{"id" => @selected})}
  """
  use Controller, :live_view

  alias Controller.Sky.{Astro, Pointing}

  @impl true
  def mount(_params, %{"id" => id}, socket) do
    if connected?(socket) and id, do: Mount.subscribe(id)
    {:ok, assign(socket, id: id, snap: snapshot(id)), layout: false}
  end

  def mount(_params, _session, socket), do: {:ok, assign(socket, id: nil, snap: nil), layout: false}

  @impl true
  def handle_info({:mount, %{id: id} = snap}, %{assigns: %{id: id}} = socket), do: {:noreply, assign(socket, snap: snap)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp snapshot(nil), do: nil

  defp snapshot(id) do
    ref = Enum.find(Mount.list(), &(&1.id == id)) || id
    Mount.snapshot(ref)
  catch
    _, _ -> nil
  end

  @impl true
  def render(assigns) do
    {motion, word} = motion(assigns.snap)
    {where, detail} = where(assigns.snap, assigns.id)
    assigns = assign(assigns, motion: motion, word: word, where: where, detail: detail)

    ~H"""
    <div class="ctl-status" role="status" aria-live="off">
      <span class={["ctl-motion", "ctl-#{@motion}"]}><i class="ctl-lamp" aria-hidden="true"></i><strong>{@word}</strong></span>
      <span :if={@where} class="ctl-where"><strong>{@where}</strong><span>{@detail}</span></span>
    </div>
    """
  end

  # what the mount is doing, in a word: a lamp for the eye, the word for everyone
  defp motion(nil), do: {"none", "No mount"}
  defp motion(%{connected: false}), do: {"down", "Not answering"}

  defp motion(%{axes: axes} = snap) do
    slewing = Enum.any?(axes, fn {_, a} -> a[:goto_pending] == true or abs(a[:deg_per_s] || 0.0) > 0.1 end)

    cond do
      slewing -> {"slewing", "Slewing"}
      snap[:tracking] not in [nil, :off] -> {"tracking", "Tracking"}
      true -> {"still", "Still"}
    end
  end

  defp motion(_), do: {"none", "No mount"}

  # where it points: on the sky once alignment (or home) says, else the axes' own angles
  defp where(%{axes: %{ra: ra, dec: dec}} = snap, id) do
    ctx = Pointing.context(DateTime.utc_now(), id)

    case Pointing.scope_radec(snap, ctx) do
      {r, d} ->
        {alt, az} = Astro.alt_az(r, d, ctx.site.lat, Astro.lst_deg(ctx.now, ctx.site.lon))
        {"RA #{hms(r)} · Dec #{dms(d)}", "#{round(alt)}° up · #{compass(az)}"}

      _ ->
        {"RA axis #{deg(ra.degrees)} · Dec axis #{deg(dec.degrees)}", "Not on the sky yet: set home or align"}
    end
  rescue
    _ -> {nil, nil}
  end

  defp where(_, _), do: {nil, nil}

  defp hms(ra) do
    h = Astro.norm360(ra) / 15
    m = (h - trunc(h)) * 60
    "#{trunc(h)}h #{String.pad_leading(to_string(trunc(m)), 2, "0")}m"
  end

  defp dms(d) do
    sign = if d < 0, do: "−", else: "+"
    a = abs(d)
    "#{sign}#{trunc(a)}° #{String.pad_leading(to_string(trunc((a - trunc(a)) * 60)), 2, "0")}′"
  end

  defp deg(x), do: "#{if x < 0, do: "−", else: "+"}#{:erlang.float_to_binary(abs(x) * 1.0, decimals: 1)}°"

  defp compass(az), do: Enum.at(~w(N NE E SE S SW W NW), round(Astro.norm360(az) / 45) |> rem(8))
end
