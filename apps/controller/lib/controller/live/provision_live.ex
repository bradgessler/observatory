defmodule Controller.ProvisionLive do
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

  @steps [card: "Card", role: "Job", machine: "Machine", network: "Network", write: "Write"]

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Provision.subscribe()
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
       wifi_ssid: "",
       wifi_psk: "",
       job: Provision.status(),
       ready: Provision.ready?(),
       notice: nil
     )}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    step = step_of(params["step"])
    {:noreply, assign(socket, step: step, page_title: "Stamp · " <> step_title(step))}
  end

  defp step_of(s) when is_binary(s) do
    Enum.find_value(@steps, :card, fn {id, _} -> if to_string(id) == s, do: id end)
  end

  defp step_of(_), do: :card

  @impl true
  def handle_info(:rescan, socket) do
    # a card can appear or be pulled at any moment; the list is never stale
    Process.send_after(self(), :rescan, 3_000)
    disks = Provision.disks()
    disk = if socket.assigns.disk in Enum.map(disks, & &1.id), do: socket.assigns.disk
    {:noreply, assign(socket, disks: disks, disk: disk)}
  end

  def handle_info({:provision, job}, socket), do: {:noreply, assign(socket, job: job)}
  def handle_info({:settings, "night", v}, socket), do: {:noreply, assign(socket, night: v)}
  def handle_info({:settings, _, _}, socket), do: {:noreply, socket}

  # -- choices ---------------------------------------------------------------------------
  # Tapping a choice is also the way forward: an option that needs confirming
  # with a second key is an option asked twice.

  @impl true
  def handle_event("pick", %{"disk" => id}, socket) do
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

  def handle_event("details", params, socket) do
    {:noreply,
     assign(socket,
       hostname: params["hostname"] || socket.assigns.hostname,
       wifi_ssid: params["wifi_ssid"] || socket.assigns.wifi_ssid,
       wifi_psk: params["wifi_psk"] || socket.assigns.wifi_psk
     )}
  end

  def handle_event("go", %{"step" => step}, socket), do: {:noreply, to_step(socket, step_of(step))}

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
        <.back navigate={back_to(@step)} label={back_label(@step)} />
        <.title>{step_title(@step)}</.title>
        <.actions><.help href={~p"/docs/provision"} label="stamping a box" /></.actions>
      </:header>

      <%= if working?(@job) do %>
        <.job job={@job} hostname={@hostname} />
      <% else %>
        <ol class="flow-steps flow-5" aria-label="stamping steps">
          <li :for={{id, label} <- steps()} class={state(id, @step)} aria-current={if id == @step, do: "step"}>
            {label}<span :if={state(id, @step) == "done"} role="img" aria-label="done"> ✓</span>
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
    <.card>
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

      <div :if={@disks == []} class="empty">
        <p>Nothing plugged in.</p>
        <.hint>Put in a card or a drive. Built-in drives never appear.</.hint>
      </div>

      <.hint :if={@disks != []}>Everything on the card you pick is erased.</.hint>
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

  # 4. How you reach it: its name, your Wi-Fi, and whether the door is open.
  defp step_card(%{step: :network} = assigns) do
    ~H"""
    <.card title="Reaching It">
      <form phx-change="details" class="box-details" aria-label="name and network">
        <label>
          Name
          <input name="hostname" type="text" autocomplete="off" value={@hostname} class="field" />
        </label>
        <label>
          Wi-Fi network
          <input name="wifi_ssid" type="text" autocomplete="off" value={@wifi_ssid} class="field" placeholder="Leave blank" />
        </label>
        <label>
          Wi-Fi password
          <input name="wifi_psk" type="password" autocomplete="off" value={@wifi_psk} class="field" />
        </label>
      </form>

      <.kv label="Answers at" value={"#{@hostname}.local"} />
      <.kv label="Otherwise" value={"Brings up #{@hostname}-setup for you to join"} />
    </.card>

    <.card title="The Door">
      <.picks label="how open the box is">
        <:pick :for={f <- Templates.flavours()} on={@flavour == f.id} click="flavour" value={%{id: f.id}} name={f.name} note={f.blurb} />
      </.picks>

      <.hint :if={Templates.flavour(@flavour).warn} class="err">{Templates.flavour(@flavour).warn}</.hint>
    </.card>

    <.row class="flow-next">
      <.btn variant="primary" phx-click="go" phx-value-step="write">Next</.btn>
    </.row>
    """
  end

  # 5. What is about to happen, then the one key that does it.
  defp step_card(%{step: :write} = assigns) do
    assigns = assign(assigns, plan: Templates.describe(plan_opts(assigns)))

    ~H"""
    <.card>
      <.kv label="Card" value={card_words(@disks, @disk)} />
      <.kv label="Box" value={"#{@plan.template} on a #{@plan.target}"} />
      <.kv label="Door" value={@plan.flavour} />
      <.kv label="Network" value={@plan.network} />

      <.hint :if={@disk} class="err">Everything on {@disk} is erased.</.hint>
      <.hint :if={is_nil(@disk)}>No card chosen yet.</.hint>

      <.row>
        <.btn
          variant="primary"
          phx-click="start"
          disabled={is_nil(@disk) or @ready != :ok}
          data-confirm={"Erase everything on #{@disk} and write a new Observatory onto it?"}
        >
          Write It
        </.btn>
        <.btn patch={~p"/provision/card"}>Change the card</.btn>
      </.row>
    </.card>

    <.hint>A first build of a machine takes about ten minutes. After that, about two.</.hint>
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

      <.row>
        <.btn :if={@job.running} phx-click="cancel" data-confirm="Stop now? The card will be half written and must be done again.">Stop</.btn>
        <.btn :if={!@job.running} patch={~p"/provision/card"}>Stamp Another</.btn>
      </.row>
    </.card>
    """
  end

  # -- words -------------------------------------------------------------------------------

  defp step_title(:card), do: "The Card"
  defp step_title(:role), do: "What It Does"
  defp step_title(:machine), do: "The Machine"
  defp step_title(:network), do: "The Network"
  defp step_title(:write), do: "Write It"

  defp back_to(:card), do: ~p"/"
  defp back_to(:role), do: ~p"/provision/card"
  defp back_to(:machine), do: ~p"/provision/role"
  defp back_to(:network), do: ~p"/provision/machine"
  defp back_to(:write), do: ~p"/provision/network"

  defp back_label(:card), do: "Home"
  defp back_label(step), do: step_title(prev(step))

  defp prev(:role), do: :card
  defp prev(:machine), do: :role
  defp prev(:network), do: :machine
  defp prev(:write), do: :network

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

  defp card_words(disks, id) do
    case Enum.find(disks, &(&1.id == id)) do
      nil -> "None chosen"
      d -> "#{d.name}, #{d.size}, #{d.id}"
    end
  end

  defp plan_opts(a),
    do: [template: a.template, target: a.target, flavour: a.flavour, hostname: a.hostname, wifi: %{ssid: a.wifi_ssid, psk: a.wifi_psk}]

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
