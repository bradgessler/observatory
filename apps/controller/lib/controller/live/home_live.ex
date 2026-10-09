defmodule Controller.HomeLive do
  @moduledoc """
  The front door: the scopes themselves, drawn and live, then (on a phone or
  tablet, where there's no sidebar) every page, grouped, each a key with its
  name and one line saying what it is. The list is `Controller.Nav`'s, drawn
  by `Controller.Components.Menu`, the same as the sidebar's: on a wide
  screen the sidebar shows it, so Home doesn't show it twice.

  Keep the list honest: if something is in it, it works; if it stops being
  useful it leaves. The one-liners double as the reason each thing exists.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings


  @impl true
  def mount(_params, _session, socket) do
    boxes? = Process.whereis(Telescope.Boxes) != nil

    if connected?(socket) do
      Settings.subscribe()
      Telescope.subscribe("tracker")
      if boxes?, do: Telescope.Boxes.subscribe()
      send(self(), :rescan)
    end

    {:ok,
     socket
     |> assign(page_title: "Home", night: Settings.get("night", false), mounts: [], refs: %{}, notice: nil, snaps: %{}, holding: %{}, subscribed: MapSet.new(), simulating: false, interrupted: %{})
     |> assign(offers: if(boxes?, do: offers(Telescope.Boxes.list()), else: []))
     |> rescan()}
  end

  @impl true
  def handle_info(:rescan, socket) do
    Process.send_after(self(), :rescan, 3_000)
    {:noreply, rescan(socket)}
  end

  def handle_info({:mount, snap}, socket), do: {:noreply, assign(socket, snaps: Map.put(socket.assigns.snaps, snap.id, snap))}

  def handle_info({:tracker, id, status}, socket) do
    {:noreply, assign(socket, holding: Map.put(socket.assigns.holding, id, status && status.name))}
  end

  # a telescope found on the network, or one that just joined: offer it, and
  # rescan so its mount shows up the moment it is connected
  def handle_info({:boxes, boxes}, socket), do: {:noreply, socket |> assign(offers: offers(boxes)) |> rescan()}

  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  # One badge per mount, live. Subscribe once per id, ever: a driver that
  # restarts must not double the 250 ms traffic into this page.
  defp rescan(socket) do
    refs = Map.new(safe(fn -> Mount.list() end) || [], &{&1.id, &1})
    socket = assign(socket, simulating: safe(fn -> Mount.Discovery.simulator?() end) == true)

    subscribed =
      Enum.reduce(refs, socket.assigns.subscribed, fn {id, ref}, acc ->
        if MapSet.member?(acc, id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, id))
      end)

    snaps = Map.new(refs, fn {id, ref} -> {id, socket.assigns.snaps[id] || safe(fn -> Mount.snapshot(ref) end)} end)
    holding = Map.new(refs, fn {id, _} -> {id, socket.assigns.holding[id] || holding_of(id)} end)
    # real telescopes first, the way pages pick one to drive (Mount.default/1)
    ids = refs |> Map.keys() |> Enum.sort_by(&{Mount.simulated?(&1), &1})
    # a hold the box went down in the middle of, for a mount that answers again (#99)
    interrupted = for id <- ids, match?(%{connected: true}, snaps[id]), h = safe(fn -> Controller.Sky.Tracker.interrupted(id) end), into: %{}, do: {id, h}
    assign(socket, mounts: ids, refs: refs, snaps: snaps, holding: holding, subscribed: subscribed, interrupted: interrupted)
  end

  defp holding_of(id) do
    case safe(fn -> Controller.Sky.Tracker.status(id) end) do
      %{name: name} -> name
      _ -> nil
    end
  end

  defp pose_of(nil), do: nil

  defp pose_of(snap) do
    ctx = Controller.Sky.Pointing.context(DateTime.utc_now(), snap.id)
    Controller.Components.Scope.pose_from(snap, ctx, tracker: Controller.Sky.Tracker.status(snap.id))
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end

  # boxes that say their node name and are not connected yet
  defp offers(boxes), do: Enum.filter(boxes, &(&1.node && !&1.connected))

  # which box a mount is on, when it is not this machine
  defp where(%{node: node}) when node != node(), do: node |> to_string() |> String.split("@") |> List.last() |> String.replace_suffix(".local", "")
  defp where(_), do: nil

  @impl true
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("box_connect", %{"node" => node}, socket) do
    notice = if Telescope.Boxes.connect(node) == :ok, do: nil, else: "No answer from #{node}"
    {:noreply, socket |> assign(offers: offers(Telescope.Boxes.list())) |> rescan() |> assign(notice: notice)}
  end

  # The mount isn't answering (switched off, cable still in): keep playing
  # against a simulator, and make it this browser's telescope.
  def handle_event("simulator", %{"on" => on}, socket) do
    on? = on == "true"
    safe(fn -> Mount.Discovery.simulator(on?) end)

    if on?,
      do: {:noreply, push_navigate(socket, to: ~p"/telescope/sim-eq?#{[return: "/"]}")},
      else: {:noreply, rescan(socket)}
  end

  # Back to what was being held when the box went down: a Go To, tapped
  def handle_event("resume", %{"id" => id}, socket) do
    with %{target: t} <- socket.assigns.interrupted[id],
         ref when not is_nil(ref) <- socket.assigns.refs[id] do
      ctx = Controller.Sky.Pointing.context(DateTime.utc_now(), id)
      # the Moon and the planets have moved on since
      obj = Enum.find(Controller.Sky.Ephemeris.objects(ctx.now, ctx.site), &(&1.id == t.id)) || t

      case Controller.Sky.Pointing.slew(ref, safe(fn -> Mount.snapshot(ref) end), obj, ctx, track: Settings.get("auto_track", true)) do
        {:ok, _, _} ->
          Controller.Sky.Tracker.forget_interrupted(id)
          {:noreply, socket |> assign(notice: "Going back to #{obj.name}") |> rescan()}

        # a flip, or anything else that needs its page: go there
        {:error, {:flip, _}} ->
          {:noreply, push_navigate(socket, to: ~p"/object/#{t.id || "none"}?#{[mount: id]}")}

        # which side the counterweight is on, only guessed: its page asks, under its Go To (#113)
        {:error, :counterweight_unknown} ->
          {:noreply, push_navigate(socket, to: ~p"/object/#{t.id || "none"}?#{[mount: id, ask: "counterweight"]}")}

        {:error, e} ->
          {:noreply, assign(socket, notice: Controller.Sky.Pointing.refusal_words(e, obj.name))}
      end
    else
      _ -> {:noreply, socket}
    end
  end

  def handle_event("forget_hold", %{"id" => id}, socket) do
    Controller.Sky.Tracker.forget_interrupted(id)
    {:noreply, rescan(socket)}
  end

  def handle_event("night", _, socket) do
    v = !socket.assigns.night
    Settings.put("night", v)
    {:noreply, assign(socket, night: v)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="home" night={@night}>
      <:header>
        <span class="tb-over">Observatory</span>
        <.title>Home</.title>
        <.actions>
          <button class="ghost night-key" phx-click="night" aria-label="Night mode" aria-pressed={to_string(@night)}>◐</button>
          <.stop />
        </.actions>
      </:header>

      <%!-- the scopes themselves, drawn and live, before any list of pages --%>
      <section :if={@mounts != []} class="home-scopes" aria-label="Scopes">
        <Controller.Components.ScopeBadge.badge
          :for={id <- @mounts}
          id={id}
          snap={@snaps[id]}
          pose={pose_of(@snaps[id])}
          holding={@holding[id]}
          where={where(@refs[id])}
          navigate={if match?(%{connected: false}, @snaps[id]), do: ~p"/devices/mount/#{id}", else: ~p"/setup/#{id}"}
        />
      </section>

      <%!-- a telescope on the network this machine has not joined yet --%>
      <section :if={@offers != []} class="home-offers" aria-label="Telescopes on this network">
        <.card :for={b <- @offers}>
          <.item label={"#{b.name} is on this network"} detail={"#{b.ip} · #{b.node}"}>
            <.btn variant="primary" phx-click="box_connect" phx-value-node={b.node} aria-label={"Connect #{b.name}"}>Connect</.btn>
          </.item>
        </.card>
      </section>

      <%!-- the box went down mid-hold (an upgrade, a reboot): offer it back, never move on its own --%>
      <section :for={{id, h} <- @interrupted} class="home-quiet" aria-label="Interrupted hold" role="status">
        <p>
          <strong>Was holding {h.target.name} when the box restarted.</strong>
          <span class="dim">The mount kept its place; the sky moved on. Go To finds it again and holds it.</span>
        </p>
        <.btn variant="primary" phx-click="resume" phx-value-id={id}>Go To {h.target.name}</.btn>
        <.btn phx-click="forget_hold" phx-value-id={id}>Forget</.btn>
      </section>

      <%!-- a mount on the cable that doesn't answer: most likely switched off --%>
      <section :if={quiet = Enum.find(@mounts, &match?(%{connected: false}, @snaps[&1]))} class="home-quiet" aria-label="Mount not answering" role="status">
        <p>
          <strong>{Controller.Components.ScopeBadge.short(quiet)} isn't answering.</strong>
          <span class="dim">The cable is in; is the mount switched on? It connects by itself when it is.</span>
        </p>
        <.btn :if={!@simulating} phx-click="simulator" phx-value-on="true">Use the Simulator</.btn>
        <.btn navigate={~p"/devices/mount/#{quiet}"}>Details ›</.btn>
      </section>
      <section :if={@simulating} class="home-quiet" aria-label="Simulator">
        <p><strong>A simulator is running</strong> <span class="dim">beside the real mount, so the pages work while it's off.</span></p>
        <.btn phx-click="simulator" phx-value-on="false">Stop the Simulator</.btn>
      </section>

      <p :if={@mounts == []} class="home-lede">
        No mount connected yet: plug the telescope cable into this machine.
      </p>

      <%!-- every page; the sidebar has it on a wide screen, so this is for phones and tablets --%>
      <div class="home-menu"><Controller.Components.Menu.menu variant="list" /></div>
      <.notice notice={@notice} />
    </.page>
    """
  end
end
