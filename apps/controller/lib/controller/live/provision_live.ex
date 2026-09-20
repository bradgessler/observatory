defmodule Controller.ProvisionLive do
  @moduledoc """
  Stamping a box: put a card in, say what the box is for, give it a network,
  and write it.

  The page is a running commentary. Writing a card takes minutes and a first
  build takes ten, so at every moment it says which step it is on, what that
  step is doing right now, and what the tools themselves are saying. A person
  should never have to wonder whether it is working or wedged.

  It also refuses to be dangerous: only removable disks are ever listed, the
  card is checked again immediately before the write, and the card's contents
  are spelled out before anything happens.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings

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
       page_title: "Stamp a Box",
       night: Settings.get("night", false),
       disks: [],
       disk: nil,
       template: :observatory,
       target: :rpi4,
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

  @impl true
  def handle_event("pick", %{"disk" => id}, socket), do: {:noreply, assign(socket, disk: id)}
  def handle_event("template", %{"id" => id}, socket), do: {:noreply, assign(socket, template: String.to_existing_atom(id))}
  def handle_event("target", %{"id" => id}, socket), do: {:noreply, assign(socket, target: String.to_existing_atom(id))}
  def handle_event("flavour", %{"id" => id}, socket), do: {:noreply, assign(socket, flavour: String.to_existing_atom(id))}

  def handle_event("details", params, socket) do
    {:noreply,
     assign(socket,
       hostname: params["hostname"] || socket.assigns.hostname,
       wifi_ssid: params["wifi_ssid"] || socket.assigns.wifi_ssid,
       wifi_psk: params["wifi_psk"] || socket.assigns.wifi_psk
     )}
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

  def handle_event("cancel", _, socket) do
    Provision.cancel()
    {:noreply, socket}
  end

  # -- render ----------------------------------------------------------------------------

  @impl true
  def render(assigns) do
    assigns = assign(assigns, plan: Provision.Templates.describe(plan_opts(assigns)))

    ~H"""
    <.page id="provision" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" />
        <.title>Stamp a Box</.title>
        <.actions><.help href={~p"/docs/provision"} label="stamping a box" /></.actions>
      </:header>

      <.hint :if={@ready != :ok} class="err" role="alert">{elem(@ready, 1)}</.hint>

      <%= if @job.running or @job.done or @job.error do %>
        <.card title={if @job.running, do: "Working", else: "Finished"} class="wide">
          <:aside>
            <span role="status" aria-live="polite">
              <.badge on={@job.done} warn={@job.error != nil}>{overall(@job)}</.badge>
            </span>
          </:aside>

          <%!-- every step, with what it is doing right now --%>
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

          <%!-- what the tools themselves are saying, so ten quiet minutes still look alive --%>
          <details :if={@job.log != []} class="job-log" open={@job.running}>
            <summary>What the tools are saying</summary>
            <pre>{@job.log |> Enum.take(12) |> Enum.reverse() |> Enum.join("\n")}</pre>
          </details>

          <.hint :if={@job.error} class="err" role="alert">{@job.error}</.hint>

          <.hint :if={@job.done}>
            Put the card in the Pi and power it up. It answers at
            <strong>{@hostname}.local</strong> once it has booted, which takes about half a minute.
          </.hint>

          <.row>
            <.btn :if={@job.running} phx-click="cancel" data-confirm="Stop now? The card will be half written and must be done again.">Stop</.btn>
            <.btn :if={!@job.running} navigate={~p"/provision"}>Stamp Another</.btn>
          </.row>
        </.card>
      <% else %>
        <%!-- 1. the card --%>
        <.card title="The Card">
          <.hint>
            Only removable disks are listed, so this page cannot offer you the machine's own drive.
            Everything on the card you choose will be erased.
          </.hint>

          <.item :for={d <- @disks} label={d.name} detail={"#{d.size} · #{d.id}#{if d.mounted != [], do: " · mounted at #{Enum.join(d.mounted, ", ")}"}"}>
            <.btn variant={if @disk == d.id, do: "primary", else: "default"} phx-click="pick" phx-value-disk={d.id}>
              {if @disk == d.id, do: "Chosen", else: "Choose"}
            </.btn>
          </.item>

          <.hint :if={@disks == []}>No card or drive is plugged in. Put one in and it appears here.</.hint>
        </.card>

        <%!-- 2. what the box is for --%>
        <.card title="What This Box Is For">
          <.item :for={t <- Provision.templates()} label={t.name} detail={t.blurb}>
            <.btn variant={if @template == t.id, do: "primary", else: "default"} phx-click="template" phx-value-id={t.id}>
              {if @template == t.id, do: "Chosen", else: "Choose"}
            </.btn>
          </.item>

          <.hint>{Provision.Templates.get(@template).wants}</.hint>

          <.seg label="which machine">
            <:opt :for={t <- Provision.targets()} on={@target == t.id} click="target" value={%{id: t.id}}>{t.name}</:opt>
          </.seg>

          <.seg label="how open the box is">
            <:opt :for={f <- Provision.Templates.flavours()} on={@flavour == f.id} click="flavour" value={%{id: f.id}}>{f.name}</:opt>
          </.seg>

          <.hint>{Provision.Templates.flavour(@flavour).blurb}</.hint>
          <.hint :if={Provision.Templates.flavour(@flavour).warn} class="err">{Provision.Templates.flavour(@flavour).warn}</.hint>
        </.card>

        <%!-- 3. how it gets on a network --%>
        <.card title="How It Gets On A Network">
          <.hint>
            Give it your Wi-Fi and it joins that. Leave it blank and it brings up a network of
            its own, which is how you reach it in a field with no signal. Either way it falls
            back to its own network when yours is not there, so a box is never unreachable.
          </.hint>

          <form phx-change="details" class="box-details" aria-label="box details">
            <label>Name<input name="hostname" type="text" autocomplete="off" value={@hostname} class="field" /></label>
            <label>Wi-Fi network<input name="wifi_ssid" type="text" autocomplete="off" value={@wifi_ssid} class="field" placeholder="leave blank for its own" /></label>
            <label>Wi-Fi password<input name="wifi_psk" type="password" autocomplete="off" value={@wifi_psk} class="field" /></label>
          </form>

          <.kv label="Reaches" value={"#{@hostname}.local, and its own network when yours is not there"} />
        </.card>

        <%!-- 4. do it --%>
        <.card title="Write It">
          <div class="state-line">
            <strong>{@plan.template} · {@plan.target} · {@plan.flavour}</strong>
            <span class="dim">{@plan.network}</span>
          </div>

          <.hint :if={@disk}>
            <strong>Everything on {@disk} will be erased.</strong>
            The first build of a machine takes about ten minutes; after that it is about two.
          </.hint>

          <.hint>Writing to a card needs administrator rights. If nothing happens, run <code>sudo -v</code> in a terminal once and try again.</.hint>

          <.row>
            <.btn
              variant="primary"
              phx-click="start"
              disabled={is_nil(@disk) or @ready != :ok}
              data-confirm={"Erase everything on #{@disk} and write a new Observatory onto it?"}
            >
              {if @disk, do: "Write It", else: "Choose a card first"}
            </.btn>
          </.row>
        </.card>
      <% end %>

      <.notice notice={@notice} />
    </.page>
    """
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
