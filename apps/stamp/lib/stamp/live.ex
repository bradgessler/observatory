defmodule Stamp.Live do
  @moduledoc """
  Stamping a box, one decision at a time.

  Five screens, each asking one thing: which card, what the box is for, which
  machine, how you reach it, and then writing it. Cramming those onto a page
  produces a wall of choices where none of them look important; split up, each
  screen has room for the option to say what it means, and a phone can show it
  without a pinch.

  State lives in the LiveView and the screens are `push_patch`es, so moving
  between them is instant and nothing is lost going back. The URL is the step,
  so Back in the browser does the obvious thing.

  It refuses to be dangerous: only removable disks are ever listed, the card is
  checked again in the moment before writing, and the card is named in the
  confirmation.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Provision.Templates

  @steps [card: "SD card", role: "Role", machine: "Board", network: "Network", write: "Build"]

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Provision.subscribe()
      Provision.Terminal.subscribe()
      Settings.subscribe()
      send(self(), :rescan)
    end

    {:ok,
     socket
     |> assign(
       night: Settings.get("night", false),
       disks: [],
       disk: nil,
       template: :observatory,
       target: :rpi4,
       touched_target: false,
       flavour: :prod,
       hostname: "observatory",
       # nil: the access point's SSID follows the hostname until someone types one
       ap_ssid: nil,
       ap_psk: Provision.Scripts.suggest_password(),
       wifi_ssid: "",
       wifi_psk: "",
       wifi_psk_typed: false,
       job: Provision.status(),
       ready: Provision.ready?(),
       scripts: Provision.Scripts.list(),
       saved: nil,
       pending: nil,
       local: local?(socket),
       allow_lan: Provision.Terminal.allow_lan?(),
       notice: nil
     )
     |> then(&assign(&1, can_type: &1.assigns.local or &1.assigns.allow_lan))
     |> remembered()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    step = step_of(params["step"])
    {:noreply, assign(socket, step: step, page_title: "Stamp · " <> step_title(step))}
  end

  defp step_of("run"), do: :run

  defp step_of(s) when is_binary(s) do
    Enum.find_value(@steps, :card, fn {id, _} -> if to_string(id) == s, do: id end)
  end

  defp step_of(_), do: :card

  @impl true
  def handle_info(:rescan, socket) do
    # a card can appear or be pulled at any moment; the list is never stale.
    # Neither is the answer to "can this machine write at all": a tool installed
    # while the page is open should stop it complaining, without a reload.
    Process.send_after(self(), :rescan, 3_000)
    disks = Provision.disks()
    disk = if socket.assigns.disk in Enum.map(disks, & &1.id), do: socket.assigns.disk
    {:noreply, assign(socket, disks: disks, disk: disk, ready: Provision.ready?())}
  end

  def handle_info({:provision, job}, socket), do: {:noreply, assign(socket, job: job)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  def handle_info({:terminal, :output, data}, socket),
    do: {:noreply, push_event(socket, "term_output", %{data: Base.encode64(data)})}

  def handle_info({:terminal, :exit, _}, socket), do: {:noreply, socket}

  def handle_info({:terminal, :allow_lan, on?}, socket),
    do: {:noreply, assign(socket, allow_lan: on?, can_type: socket.assigns.local or on?)}

  # -- choices ---------------------------------------------------------------------------
  # Tapping a choice is also the way forward: an option that needs confirming
  # with a second key is an option asked twice.

  @impl true
  # STOP is on every page: every mount in reach
  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  def handle_event("pick", %{"id" => id}, socket) do
    {:noreply, socket |> assign(disk: id) |> to_step(:role)}
  end

  def handle_event("template", %{"id" => id}, socket) do
    template = String.to_existing_atom(id)

    # the machine follows the job unless a person has said otherwise
    socket =
      if socket.assigns.touched_target,
        do: socket,
        else: assign(socket, target: Templates.get(template).wants)

    {:noreply, socket |> assign(template: template) |> to_step(:machine)}
  end

  def handle_event("target", %{"id" => id}, socket) do
    {:noreply,
     socket
     |> assign(target: String.to_existing_atom(id), touched_target: true)
     |> to_step(:network)}
  end

  def handle_event("flavour", %{"id" => id}, socket) do
    {:noreply, assign(socket, flavour: String.to_existing_atom(id))}
  end

  # Each card is its own form, so a change carries only that card's fields;
  # anything not sent keeps its value.
  def handle_event("details", params, socket) do
    a = socket.assigns

    hostname = params["hostname"] || a.hostname

    # typing the hostname, or nothing, puts the SSID back to following it
    ap_ssid =
      case params["ap_ssid"] do
        nil -> a.ap_ssid
        ssid when ssid in ["", hostname] -> nil
        ssid -> ssid
      end

    socket =
      assign(socket,
        hostname: hostname,
        ap_ssid: ap_ssid,
        ap_psk: params["ap_psk"] || a.ap_psk,
        wifi_ssid: params["wifi_ssid"] || a.wifi_ssid
      )

    # A saved home password is never put in the page, so the field arrives
    # empty until someone types in it. Empty and untouched means "keep the
    # saved one"; once typed in, the field says what the password is.
    socket =
      case params["wifi_psk"] do
        nil -> socket
        "" when not a.wifi_psk_typed -> socket
        psk -> assign(socket, wifi_psk: psk, wifi_psk_typed: true)
      end

    {:noreply, socket}
  end

  def handle_event("go", %{"step" => step}, socket), do: {:noreply, to_step(socket, step_of(step))}

  # Stamp: save the configuration (a script, so it can be stamped again without
  # the five screens) and run it. Saving is incidental; stamping is the point.
  def handle_event("save_script", _, %{assigns: %{ap_psk: psk}} = socket) when psk != "" and (byte_size(psk) < 8 or byte_size(psk) > 63) do
    {:noreply, socket |> assign(notice: "The access point password is 8 to 63 characters, or none.") |> to_step(:network)}
  end

  def handle_event("save_script", _, socket) when byte_size(socket.assigns.hostname) == 0 do
    {:noreply, socket |> assign(notice: "A hostname is required.") |> to_step(:network)}
  end

  def handle_event("save_script", _, socket) do
    path = Provision.Scripts.save(plan_opts(socket.assigns))

    {:noreply,
     socket
     |> assign(scripts: Provision.Scripts.list())
     |> run(path)
     |> to_step(:run)}
  end

  def handle_event("run_script", %{"id" => path}, socket) do
    # only a script from the list: the page never types a path it was handed
    if Enum.any?(socket.assigns.scripts, &(&1.path == path)),
      do: {:noreply, socket |> run(path) |> to_step(:run)},
      else: {:noreply, socket}
  end

  # The hook has drawn its screen and knows how big it is. A shell is started
  # at that size if none is running; anything waiting to be typed goes in.
  def handle_event("term_open", %{"cols" => cols, "rows" => rows}, socket) do
    if may_type?(socket), do: Provision.Terminal.open(cols, rows)

    socket = push_event(socket, "term_output", %{data: Base.encode64(Provision.Terminal.scrollback())})

    # a device that may not type does not get a command typed for it either
    case socket.assigns.pending do
      line when is_binary(line) ->
        # a fresh shell: this waits for its first prompt (Provision.Terminal)
        if may_type?(socket), do: Provision.Terminal.run(line)
        {:noreply, assign(socket, pending: nil)}

      nil ->
        {:noreply, socket}
    end
  end

  # Keystrokes, the sudo password among them, arrive under "keys", which the
  # log filters. The shell runs as the user, so input is taken only from this
  # machine, or from other devices once someone at this machine has allowed it.
  def handle_event("term_input", %{"keys" => keys}, socket) do
    if may_type?(socket) do
      unless Provision.Terminal.running?(), do: Provision.Terminal.open()
      Provision.Terminal.input(keys)
    end

    {:noreply, socket}
  end

  # The keys a phone's keyboard does not have.
  def handle_event("term_key", %{"key" => key}, socket) do
    bytes = %{"enter" => "\r", "yes" => "y\r", "ctrl_c" => "\x03"}[key]
    if bytes && may_type?(socket), do: Provision.Terminal.input(bytes)
    {:noreply, socket}
  end

  # Only a page on this machine can open the shell to other devices.
  def handle_event("allow_lan", %{"on" => on}, socket) do
    if socket.assigns.local, do: Provision.Terminal.allow_lan(on == "true")
    {:noreply, socket}
  end

  def handle_event("start", _, socket) do
    a = socket.assigns

    opts = [
      disk: a.disk,
      template: a.template,
      target: a.target,
      flavour: a.flavour,
      hostname: a.hostname,
      wifi: %{ssid: a.wifi_ssid, psk: a.wifi_psk}
    ]

    case Provision.start(opts) do
      :ok -> {:noreply, assign(socket, notice: nil)}
      {:error, why} -> {:noreply, assign(socket, notice: {to_string(why), System.unique_integer([:positive])})}
    end
  end

  # Putting the finished job away is what brings the five screens back: until
  # it is cleared, every step renders as the job panel instead.
  def handle_event("change", _, socket) do
    Provision.clear()
    {:noreply, socket |> assign(job: Provision.status()) |> to_step(:write)}
  end

  def handle_event("another", _, socket) do
    Provision.clear()
    {:noreply, socket |> assign(job: Provision.status(), disk: nil) |> to_step(:card)}
  end

  def handle_event("cancel", _, socket) do
    Provision.cancel()
    {:noreply, socket}
  end

  defp to_step(socket, step), do: push_patch(socket, to: ~p"/provision/#{step}")

  # -- render ----------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="provision" class="flow" night={@night}>
      <:header>
        <.back {back_link(@step)} label={back_label(@step)} section="System" />
        <.title>{step_title(@step)}</.title>
        <.actions><.help href={~p"/docs/provision"} label="stamping a box" /><.stop /></.actions>
      </:header>

      <%= if working?(@job) do %>
        <.job job={@job} hostname={@hostname} />
      <% else %>
        <ol :if={@step != :run} class="flow-steps flow-5" aria-label="stamping steps">
          <li :for={{id, label} <- steps()} class={state(id, @step)} aria-current={if id == @step, do: "step"}>
            <span class="flow-label">{label}</span><span :if={state(id, @step) == "done"} role="img" aria-label="done"> ✓</span>
          </li>
        </ol>

        <.hint :if={@ready != :ok} class="err" role="alert">{elem(@ready, 1)}</.hint>

        {step_card(assigns)}
      <% end %>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp steps, do: @steps

  defp working?(job), do: job.running or job.done or job.error != nil

  # -- one screen per decision -------------------------------------------------------------

  # 1. The card. Nothing else on this screen: the one thing that gets erased
  # deserves a page where it is the only thing you are looking at.
  defp step_card(%{step: :card} = assigns) do
    ~H"""
    <.card title="SD Card">
      <.picks :if={@disks != []} label="which card">
        <:pick
          :for={d <- @disks}
          on={@disk == d.id}
          click="pick"
          value={%{id: d.id}}
          name={d.name}
          note={"#{d.size} · #{d.id}"}
          tag={if d.mounted != [], do: "Mounted"}
        />
      </.picks>
      <.hint :if={@disks != []}>Everything on the card you pick is erased.</.hint>

      <.item :if={@disks == []} label="No removable disk" detail="Checked every 3 s; internal disks are never listed. A card that does not appear: unplug the reader and plug it back in." />
    </.card>

    <%!-- a saved stamp is an action, not a choice: it runs as it was saved --%>
    <.card :if={@scripts != []} title="Stamp Again">
      <.items label="saved stamps">
        <.item :for={sc <- @scripts} as="li" label={sc.name} detail={sc.about}>
          <.btn phx-click="run_script" phx-value-id={sc.path} aria-label={"Stamp #{sc.name}"}>Stamp</.btn>
        </.item>
      </.items>
    </.card>
    """
  end

  # 2. What it is for. Three jobs, each showing the parts it puts on the box.
  defp step_card(%{step: :role} = assigns) do
    ~H"""
    <.card>
      <.picks label="what the box is for">
        <:pick :for={t <- Provision.templates()} on={@template == t.id} click="template" value={%{id: t.id}} name={t.name} note={t.blurb}>
          <.parts parts={t.parts} />
        </:pick>
      </.picks>
    </.card>
    """
  end

  # 3. The machine. Five rows, the one that suits the job already chosen.
  defp step_card(%{step: :machine} = assigns) do
    ~H"""
    <.card>
      <.picks label="which machine">
        <:pick
          :for={t <- Provision.targets()}
          on={@target == t.id}
          click="target"
          value={%{id: t.id}}
          name={t.name}
          note={t.note}
          tag={if t.id == Templates.get(@template).wants, do: "Suits #{Templates.get(@template).name}"}
        />
      </.picks>
    </.card>
    """
  end

  # 4. Network. Standard terms, and every field starts filled in with the value
  # the box will really use: what is on screen is what goes on the card. The
  # access point is always there; the Wi-Fi client is optional.
  defp step_card(%{step: :network} = assigns) do
    ~H"""
    <.card>
      <form phx-change="details" class="box-details" aria-label="hostname">
        <label>
          Hostname
          <input name="hostname" type="text" autocomplete="off" data-1p-ignore value={@hostname} class="field" />
        </label>
      </form>
      <.kv label="mDNS" value={"#{@hostname}.local"} />
    </.card>

    <.card title="Access Point">
      <form phx-change="details" class="box-details" aria-label="access point">
        <label>
          SSID
          <input name="ap_ssid" type="text" autocomplete="off" data-1p-ignore value={ap_ssid(assigns)} class="field" />
        </label>
        <label>
          Password
          <input name="ap_psk" type="text" autocomplete="off" data-1p-ignore value={@ap_psk} class="field" />
        </label>
      </form>
      <.kv label="Security" value={if @ap_psk == "", do: "Open", else: "WPA/WPA2, AES"} />
      <.kv label="Address" value={"192.168.24.1, #{@hostname}.local"} />
      <.kv label="DHCP" value="192.168.24.10 to 250" />
      <.hint :if={bad_ssid?(ap_ssid(assigns))} class="err">An SSID is 1 to 32 bytes.</.hint>
      <.hint :if={bad_psk?(@ap_psk)} class="err">8 to 63 characters, or empty for an open network.</.hint>
      <.hint :if={@ap_psk == ""} class="err">Open network: anyone in range can join and drive the mount.</.hint>
      <.hint>No router or internet needed. The SSID follows the hostname until you change it.</.hint>
    </.card>

    <.card title="Wi-Fi Client (Optional)">
      <form phx-change="details" class="box-details" aria-label="Wi-Fi client">
        <label>
          SSID
          <input name="wifi_ssid" type="text" autocomplete="off" data-1p-ignore value={@wifi_ssid} class="field" />
        </label>
        <label>
          Password
          <input
            name="wifi_psk"
            type="password"
            autocomplete="off"
            data-1p-ignore
            value={if @wifi_psk_typed, do: @wifi_psk, else: ""}
            placeholder={if @wifi_psk != "" and not @wifi_psk_typed, do: "Saved. Type to replace"}
            class="field"
          />
        </label>
      </form>
      <%!-- The policy Firmware.Wireless runs, stated outright: this card
            changes what the access point does, so it says how. --%>
      <.kv label="Radio" value="One: client or access point, never both at once" />
      <.kv :if={@wifi_ssid == ""} label="At boot" value="Access point" />
      <.kv :if={@wifi_ssid != ""} label="At boot" value={"Joins #{@wifi_ssid} by DHCP, reachable at #{@hostname}.local"} />
      <.kv :if={@wifi_ssid != ""} label="Fallback" value="Not joined for 45 s, at boot or any time later: access point until reboot" />
    </.card>

    <.row class="flow-next">
      <.btn variant="primary" phx-click="go" phx-value-step="write">Next</.btn>
    </.row>
    """
  end

  # 5. What was chosen, and the key that turns it into a script. The page does
  # not write the card itself: that needs root, and root is asked for in a
  # terminal, which is the next screen.
  defp step_card(%{step: :write} = assigns) do
    assigns = assign(assigns, plan: Templates.describe(plan_opts(assigns)))

    ~H"""
    <.card title="Summary">
      <.kv label="Role" value={@plan.template} />
      <.kv label="Board" value={@plan.target} />
      <.kv label="Hostname" value={"#{@hostname}.local"} />
      <.kv label="Network" value={@plan.network} />
      <.kv label="SSH" value={@plan.flavour} />
    </.card>

    <%!-- SSH is what is on the box, not how it is reached: it sits with the
          build, not the network. It is also the door for network updates. --%>
    <.card title="SSH">
      <.picks label="SSH">
        <:pick :for={f <- Templates.flavours()} on={@flavour == f.id} click="flavour" value={%{id: f.id}} name={f.name} note={f.blurb} />
      </.picks>

      <.hint :if={Templates.flavour(@flavour).warn} class="err">{Templates.flavour(@flavour).warn}</.hint>
    </.card>

    <%!-- the one action, last, where the eye ends --%>
    <div class="flow-actions">
      <.hint>Builds, then writes the SD card: about ten minutes the first time for a board, about one after. sudo asks for your password; fwup asks before it writes.</.hint>
      <.btn variant="primary" phx-click="save_script">Stamp</.btn>
    </div>
    """
  end

  # 6. The stamp, running: a real terminal and nothing else. It is where the
  # build scrolls past, sudo asks for the password and fwup asks before it
  # writes. What phone input means is in the docs, not on the screen.
  defp step_card(%{step: :run} = assigns) do
    ~H"""
    <.card title={if @saved, do: Path.basename(@saved), else: "Terminal"} class="term-card">
      <:aside :if={@local}>
        <.seg label="phone input">
          <:opt on={!@allow_lan} click="allow_lan" value={%{on: "false"}}>Phone input off</:opt>
          <:opt on={@allow_lan} click="allow_lan" value={%{on: "true"}}>On</:opt>
        </.seg>
      </:aside>

      <div id="term" class="term" phx-hook="Terminal" phx-update="ignore" data-can-type={to_string(@can_type)}></div>

      <%!-- a phone keyboard has no Ctrl, and fwup's question wants a y --%>
      <.row :if={@can_type}>
        <.btn phx-click="term_key" phx-value-key="enter">Enter</.btn>
        <.btn phx-click="term_key" phx-value-key="yes" aria-label="y then Enter">y ⏎</.btn>
        <.btn phx-click="term_key" phx-value-key="ctrl_c" aria-label="control C, interrupt">Ctrl-C</.btn>
      </.row>

      <.hint :if={!@can_type}>Read-only on this device.</.hint>
    </.card>
    """
  end

  # -- while it works ----------------------------------------------------------------------

  attr :job, :map, required: true
  attr :hostname, :string, required: true

  defp job(assigns) do
    ~H"""
    <.card title={if @job.running, do: "Working", else: "Finished"} class="wide">
      <:aside>
        <span role="status" aria-live="polite">
          <.badge on={@job.done} warn={@job.error != nil}>{overall(@job)}</.badge>
        </span>
      </:aside>

      <ol class="job-steps">
        <li :for={{id, label} <- @job.order} class={step_class(@job.steps[id])}>
          <span class="job-mark" aria-hidden="true">{mark(@job.steps[id])}</span>
          <span class="job-text">
            <strong>{label}</strong>
            <span :if={@job.steps[id].detail} class="dim">{@job.steps[id].detail}</span>
          </span>
        </li>
      </ol>

      <div :if={@job.percent} class="job-bar" role="progressbar" aria-valuenow={@job.percent} aria-valuemin="0" aria-valuemax="100">
        <i style={"width: #{@job.percent}%"}></i>
        <span>{@job.percent}%</span>
      </div>

      <%!-- ten quiet minutes look wedged unless the tools keep talking --%>
      <details :if={@job.log != []} class="job-log" open={@job.running}>
        <summary>What the tools are saying</summary>
        <pre>{@job.log |> Enum.take(12) |> Enum.reverse() |> Enum.join("\n")}</pre>
      </details>

      <.hint :if={@job.error} class="err" role="alert">{@job.error}</.hint>

      <.hint :if={@job.done}>
        Put the card in and power it up. It answers at <strong>{@hostname}.local</strong> in about half a minute.
      </.hint>

      <%!-- A job that has ended must not wall off the flow. On a failure the
            choices that made it are still here, so the way out is to change
            one of them and go again, not to start from nothing. --%>
      <.row>
        <.btn :if={@job.running} phx-click="cancel" data-confirm="Stop now? The card will be half written and must be done again.">Stop</.btn>
        <.btn :if={!@job.running and @job.error != nil} variant="primary" phx-click="start">Try Again</.btn>
        <.btn :if={!@job.running and @job.error != nil} phx-click="change">Change Something</.btn>
        <.btn :if={!@job.running and @job.error == nil} phx-click="another">Stamp Another</.btn>
      </.row>
    </.card>
    """
  end

  # -- the terminal ------------------------------------------------------------------------

  # ~/ rather than /Users/you/: one line on a phone, and the same command in any
  # terminal on this machine.
  defp run_line(path) do
    case Path.relative_to(path, System.user_home!()) do
      ^path -> "sh " <> Provision.Command.quote_arg(path)
      rel -> "sh ~/" <> Provision.Command.quote_arg(rel)
    end
  end

  # Straight in if a shell is up; otherwise held until the hook opens one.
  # Stamping starts it: the script builds, then sudo and fwup each ask before
  # anything touches a card. It only starts from an idle prompt: typed into a
  # stamp already running, it could reach fwup mid-write.
  defp run(socket, path) do
    socket = assign(socket, saved: path)

    cond do
      not may_type?(socket) -> assign(socket, notice: "Read-only on this device")
      not Provision.Terminal.running?() -> assign(socket, pending: run_line(path))
      Provision.Terminal.idle?() -> tap(socket, fn _ -> Provision.Terminal.run(run_line(path)) end)
      true -> assign(socket, notice: "The terminal is busy. Ctrl-C stops what is running, then stamp again.")
    end
  end

  # Asked live rather than read from the assign: the switch can be flipped from
  # another page at any moment, and off must mean off immediately.
  defp may_type?(socket), do: socket.assigns.local or Provision.Terminal.allow_lan?()

  # This machine means loopback, or one of this machine's own addresses (the
  # page opened at its LAN address from the Mac itself).
  defp local?(socket) do
    case get_connect_info(socket, :peer_data) do
      %{address: ip} -> loopback?(ip) or own_address?(ip)
      _ -> false
    end
  end

  defp loopback?({127, _, _, _}), do: true
  defp loopback?({0, 0, 0, 0, 0, 0, 0, 1}), do: true
  defp loopback?({0, 0, 0, 0, 0, 0xFFFF, a, b}), do: loopback?({div(a, 256), rem(a, 256), div(b, 256), rem(b, 256)})
  defp loopback?(_), do: false

  defp own_address?(ip) do
    case :inet.getifaddrs() do
      {:ok, ifs} -> Enum.any?(ifs, fn {_, opts} -> {:addr, ip} in opts end)
      _ -> false
    end
  end

  # -- words -------------------------------------------------------------------------------

  defp step_title(:card), do: "SD Card"
  defp step_title(:role), do: "Role"
  defp step_title(:machine), do: "Board"
  defp step_title(:network), do: "Network"
  defp step_title(:write), do: "Build"
  defp step_title(:run), do: "Stamp"

  # Back inside the flow is a patch: a step you return to still has everything
  # you chose. Only leaving for Home is a real navigation.
  defp back_link(:card), do: %{navigate: ~p"/"}
  defp back_link(step), do: %{patch: back_to(step)}

  defp back_to(:role), do: ~p"/provision/card"
  defp back_to(:machine), do: ~p"/provision/role"
  defp back_to(:network), do: ~p"/provision/machine"
  defp back_to(:write), do: ~p"/provision/network"
  defp back_to(:run), do: ~p"/provision/write"

  defp back_label(:card), do: "Home"
  defp back_label(step), do: step_title(prev(step))

  defp prev(:role), do: :card
  defp prev(:machine), do: :role
  defp prev(:network), do: :machine
  defp prev(:write), do: :network
  defp prev(:run), do: :write

  defp state(id, now) do
    order = Keyword.keys(@steps)
    i = Enum.find_index(order, &(&1 == id))
    j = Enum.find_index(order, &(&1 == now))

    cond do
      i == j -> "now"
      i < j -> "done"
      true -> ""
    end
  end


  defp plan_opts(a),
    do: [
      template: a.template,
      target: a.target,
      flavour: a.flavour,
      hostname: a.hostname,
      ap_ssid: ap_ssid(a),
      ap_psk: a.ap_psk,
      wifi: %{ssid: a.wifi_ssid, psk: a.wifi_psk}
    ]

  defp ap_ssid(a), do: a.ap_ssid || a.hostname

  # WPA2 wants 8 to 63 characters. The firmware build refuses anything else,
  # but ten minutes into a build is a late place to find out.
  defp bad_psk?(""), do: false
  defp bad_psk?(psk), do: String.length(psk) not in 8..63

  defp bad_ssid?(ssid), do: byte_size(ssid) not in 1..32

  # The newest saved stamp is the best guess at the next one. Its choices
  # come back filled in, so stamping another card is checking, not typing.
  defp remembered(socket) do
    with [%{path: path} | _] <- socket.assigns.scripts,
         {:ok, opts} <- Provision.Scripts.load(path) do
      wifi = opts[:wifi] || %{}

      assign(socket,
        template: opts[:template] || socket.assigns.template,
        target: opts[:target] || socket.assigns.target,
        touched_target: opts[:target] != nil,
        flavour: opts[:flavour] || socket.assigns.flavour,
        hostname: opts[:hostname] || socket.assigns.hostname,
        # a saved SSID equal to the hostname was following it; keep it following
        ap_ssid: if(opts[:ap_ssid] in [nil, "", opts[:hostname]], do: nil, else: opts[:ap_ssid]),
        # a stamp from before the box had its own password gets a fresh one
        ap_psk: if(opts[:ap_psk] in [nil, ""], do: socket.assigns.ap_psk, else: opts[:ap_psk]),
        wifi_ssid: wifi[:ssid] || "",
        wifi_psk: wifi[:psk] || ""
      )
    else
      _ -> socket
    end
  end

  defp overall(%{error: e}) when is_binary(e), do: "Stopped"
  defp overall(%{done: true}), do: "Done"
  defp overall(%{running: true}), do: "Working"
  defp overall(_), do: "Idle"

  defp step_class(%{state: s}), do: "job-step job-#{s}"
  defp step_class(_), do: "job-step job-waiting"

  defp mark(%{state: :done}), do: "✓"
  defp mark(%{state: :failed}), do: "✕"
  defp mark(%{state: :running}), do: "▸"
  defp mark(_), do: "·"
end
