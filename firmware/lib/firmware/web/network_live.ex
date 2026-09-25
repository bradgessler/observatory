defmodule Firmware.Web.NetworkLive do
  @moduledoc """
  The box's own network: three screens, one job each.

    * `/network`: what the radio is doing now (client or access point, the
      SSID, the signal), the addresses to reach it at, and its power.
    * `/network/wifi`: the saved client networks (forget one) and the nearby
      ones with their signal (tap one to join).
    * `/network/join`: the SSID and password for one network.

  One LiveView, patched between the three, so the status keeps ticking and a
  scan's results are there when you come back.

  Part of the firmware, not the controller: the radio is the firmware's
  (`Firmware.Wireless`), so its page is too. A build adds it to the controller
  through `config :controller, :extensions`; a Mac never has it.

  Joining is the one action here that can cut off the phone doing it: a phone
  on the box's access point loses it the moment the radio becomes a client. The
  join screen says so first, and the 45-second fallback is what makes it safe:
  a wrong password brings the access point back.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.Settings
  alias Firmware.{Power, Wireless}

  @tick_ms 3_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@tick_ms, :tick)

    {:ok,
     socket
     |> assign(night: Settings.get("night", false), notice: nil, ssid: "")
     |> refresh()}
  end

  @impl true
  def handle_params(params, _uri, socket) do
    title =
      case socket.assigns.live_action do
        :index -> "Network"
        :wifi -> "Wi-Fi Networks"
        :join -> "Join"
      end

    {:noreply, assign(socket, page_title: title, ssid: params["ssid"] || "")}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, refresh(socket)}

  @impl true
  def handle_event("scan", _, socket) do
    notice = if Wireless.scan() == :ok, do: "Scanning", else: "Scanning is not available right now"
    {:noreply, assign(socket, notice: notice)}
  end

  def handle_event("typed", %{"ssid" => ssid}, socket), do: {:noreply, assign(socket, ssid: ssid)}

  # The password arrives as "password", which the log filters.
  def handle_event("join", %{"ssid" => ssid, "password" => password}, socket) do
    ssid = String.trim(ssid)

    cond do
      ssid == "" ->
        {:noreply, assign(socket, notice: "An SSID is required")}

      password != "" and String.length(password) not in 8..63 ->
        {:noreply, assign(socket, notice: "A WPA password is 8 to 63 characters")}

      true ->
        case Wireless.join(ssid, password) do
          :ok -> {:noreply, socket |> assign(notice: "Joining #{ssid}") |> refresh() |> push_patch(to: ~p"/network")}
          {:error, why} -> {:noreply, assign(socket, notice: "Could not join #{ssid}: #{inspect(why)}")}
        end
    end
  end

  def handle_event("forget", %{"id" => ssid}, socket) do
    case Wireless.forget(ssid) do
      :ok -> {:noreply, socket |> assign(notice: "Forgot #{ssid}") |> refresh()}
      {:error, why} -> {:noreply, assign(socket, notice: "Could not forget #{ssid}: #{inspect(why)}")}
    end
  end

  defp refresh(socket) do
    assign(socket,
      status: Wireless.status(),
      nearby: Wireless.access_points(),
      power: Power.status(),
      uptime: Power.uptime_s()
    )
  end

  # -- /network ---------------------------------------------------------------------

  @impl true
  def render(%{live_action: :index} = assigns) do
    ~H"""
    <.page id="network" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" />
        <.title>Network</.title>
        <.actions><.help href={~p"/docs/network"} label="network" /></.actions>
      </:header>

      <.card title="Wi-Fi">
        <:aside><.badge on={@status.mode != :none}>{mode_word(@status.mode)}</.badge></:aside>
        <div role="status" aria-live="polite" class="net-now">
          <%= case @status.mode do %>
            <% :home -> %>
              <p class="net-ssid">{@status.client_ssid || "Joining"}</p>
              <.signal :if={@status.signal} percent={@status.signal.signal} dbm={@status.signal.dbm} />
              <.kv :if={@status.signal} label="Band" value={band_words(@status.signal)} />
              <.kv label="Uplink" value={connection_word(@status.connection)} />
              <.kv label="Power save" value={if @status.power_save == :off, do: "Off", else: "Driver default"} />
            <% :own -> %>
              <p class="net-ssid">{@status.ap_ssid}</p>
              <.kv label="Security" value="WPA2, AES" />
              <.kv label="Clients" value={to_string(@status.clients)} />
              <.hint :if={@status.phase == :window}>
                Access point for the first {div(Application.get_env(:firmware, :ap_window_ms, 120_000), 60_000)} min after power-on, then {Enum.join(@status.networks, ", ")}; {@status.window_left_s} s left. A phone on it keeps it for this boot.
              </.hint>
              <.hint :if={@status.phase == :kept}>A phone joined in the first minutes after power-on, so it stays the access point until the next boot.</.hint>
            <% _ -> %>
              <p class="net-ssid">Radio off</p>
          <% end %>
        </div>
        <.items label="Wi-Fi">
          <.link_item patch={~p"/network/wifi"} label="Wi-Fi Networks" detail={networks_words(@status)} />
        </.items>
      </.card>

      <.card title="Addresses">
        <.kv label="mDNS" value={@status.name} />
        <.kv :for={a <- @status.addresses} label={a.ifname} value={a.address} />
        <.hint :if={@status.addresses == []}>No address yet.</.hint>
      </.card>

      <.card title="Power">
        <div role="status" aria-live="polite">
          <.kv label="Uptime" value={uptime_words(@uptime)} />
          <.kv :if={@power == :unknown} label="Supply" value="Not reported by this board" />
          <.kv :if={@power != :unknown} label="Supply" value={supply_words(@power)} />
        </div>
        <.hint :if={@power != :unknown and @power.undervoltage_since_boot} class="err">
          The supply has sagged below 4.63 V since boot. Wi-Fi drops and resets follow; give the Pi its own 5 V, 2.5 A supply.
        </.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # -- /network/wifi ----------------------------------------------------------------

  def render(%{live_action: :wifi} = assigns) do
    ~H"""
    <.page id="network-wifi" night={@night}>
      <:header>
        <.back patch={~p"/network"} label="Network" />
        <.title>Wi-Fi Networks</.title>
        <.actions><button class="btn" phx-click="scan" disabled={@status.mode == :own}>Scan</button></.actions>
      </:header>

      <.card title="Saved">
        <.items :if={@status.networks != []} label="saved networks">
          <.item :for={ssid <- @status.networks} as="li" label={ssid} detail={saved_words(ssid, @status)}>
            <.btn phx-click="forget" phx-value-id={ssid} data-confirm={"Forget #{ssid}?"} aria-label={"Forget #{ssid}"}>Forget</.btn>
          </.item>
        </.items>
        <.hint :if={@status.networks == []}>None. The radio is the access point {@status.ap_ssid} from every boot.</.hint>
      </.card>

      <.card title="Nearby">
        <.items :if={@nearby != []} label="nearby networks">
          <.link_item :for={ap <- @nearby} patch={~p"/network/join?#{[ssid: ap.ssid]}"} label={ap.ssid} detail={nearby_words(ap)}>
            <:aside><.signal percent={ap.signal} /></:aside>
          </.link_item>
          <.link_item patch={~p"/network/join"} label="Other Network" detail="Type the SSID" />
        </.items>
        <%= if @nearby == [] do %>
          <.hint :if={@status.mode == :own}>The radio cannot scan while it is the access point.</.hint>
          <.hint :if={@status.mode != :own}>Nothing heard yet. Scan to look.</.hint>
          <.items label="other network">
            <.link_item patch={~p"/network/join"} label="Other Network" detail="Type the SSID" />
          </.items>
        <% end %>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  # -- /network/join ----------------------------------------------------------------

  def render(%{live_action: :join} = assigns) do
    ~H"""
    <.page id="network-join" night={@night}>
      <:header>
        <.back patch={~p"/network/wifi"} label="Wi-Fi Networks" />
        <.title>Join</.title>
      </:header>

      <.card title={if @ssid == "", do: "Other Network", else: @ssid}>
        <form phx-submit="join" phx-change="typed" class="box-details" autocomplete="off" aria-label="join a Wi-Fi network">
          <label>
            SSID
            <input name="ssid" type="text" autocomplete="off" data-1p-ignore value={@ssid} class="field" />
          </label>
          <label>
            Password
            <input name="password" type="password" autocomplete="off" data-1p-ignore class="field" />
          </label>
          <.row><.btn variant="primary" type="submit">Join</.btn></.row>
        </form>
        <.hint :if={@status.mode == :own} class="err">
          Joining switches the radio from the access point to that network, so a phone on the access point drops off. Rejoin on that network and open {@status.name}. Not joined within 45 s: the access point comes back.
        </.hint>
        <.hint :if={@status.mode != :own}>Saved, and tried first at every boot. Empty password: an open network.</.hint>
      </.card>

      <.notice notice={@notice} />
    </.page>
    """
  end

  defp mode_word(:own), do: "Access point"
  defp mode_word(:home), do: "Client"
  defp mode_word(_), do: "Off"

  defp connection_word(:internet), do: "Internet"
  defp connection_word(:lan), do: "Local network, no internet"
  defp connection_word(_), do: "Not connected"

  defp band_words(%{band: nil}), do: "Unknown"
  defp band_words(%{band: band, channel: ch}), do: "#{band}, channel #{ch}"

  defp networks_words(%{networks: []}), do: "None saved"
  defp networks_words(%{networks: [one]}), do: "1 saved: #{one}"
  defp networks_words(%{networks: n}), do: "#{length(n)} saved"

  defp saved_words(ssid, %{client_ssid: ssid}), do: "Joined"
  defp saved_words(_, _), do: "Tried at every boot"

  defp nearby_words(ap), do: [ap.security, ap.band, ap.channel && "channel #{ap.channel}"] |> Enum.reject(&is_nil/1) |> Enum.join(", ")

  defp supply_words(%{undervoltage_now: true}), do: "Under-voltage now"
  defp supply_words(%{undervoltage_since_boot: true}), do: "Under-voltage since boot"
  defp supply_words(_), do: "OK since boot"

  defp uptime_words(s) when s < 120, do: "#{s} s"
  defp uptime_words(s) when s < 7200, do: "#{div(s, 60)} min"
  defp uptime_words(s), do: "#{div(s, 3600)} h #{div(rem(s, 3600), 60)} min"
end
