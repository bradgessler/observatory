defmodule Controller.Layouts do
  @moduledoc """
  This module holds layouts and related functionality
  used by your application.
  """
  use Controller, :html
  alias Controller.Components.{AlignmentStatus, Icons}

  # Embed all files in layouts/* within this module.
  # The default root.html.heex file contains the HTML
  # skeleton of your application, namely HTML headers
  # and other static content.
  embed_templates "layouts/*"

  @doc """
  The layout every routed LiveView renders inside (see `Controller.live_view/0`).
  On a wide screen: the sidebar of every page, the current one marked, beside
  the page. On a phone the sidebar is not drawn; Home is the list, each
  page's header links back to it, and its search key opens Search.

  Search (`Controller.Spotlight`) is rendered here, once per page, so it's
  there on every page and ⌘K always finds it.
  """
  def shell(assigns) do
    ~H"""
    <.frame current_path={assigns[:current_path]} nav_path={assigns[:nav_path]} night={assigns[:night]} telescopes={assigns[:telescopes] || []} telescope={assigns[:telescope]} alignments={assigns[:alignments] || %{}}>
      {@inner_content}
      <:search><.live_component module={Controller.Spotlight} id="spotlight" here={assigns[:current_path]} /></:search>
    </.frame>
    """
  end

  attr :current_path, :string, default: nil
  attr :nav_path, :string, default: nil, doc: "the sidebar entry to mark, when it isn't the path's (an object opened from Tonight)"
  attr :night, :boolean, default: false
  attr :telescopes, :list, default: []
  attr :telescope, :map, default: nil
  attr :alignments, :map, default: %{}, doc: "each telescope's alignment (`Controller.Alignment`), by id"
  slot :inner_block, required: true
  slot :search, doc: "Search, on a LiveView page; a page without it (a doc) links to the search page instead"

  def frame(assigns) do
    assigns = assign(assigns, current: Controller.Nav.current(assigns.nav_path || assigns.current_path), host: host())

    ~H"""
    <div class={["shell", @night && "night"]}>
      <nav class="sidebar" aria-label="Pages">
        <%!-- the telescope switcher: which scope every page here acts on. A
              native popover, no script; the choice is kept per viewer. --%>
        <div class="switcher">
          <button type="button" class="side-brand switcher-button" popovertarget="telescope-menu" aria-label={"Telescope: #{telescope_name(@telescope)}. Switch telescope"}>
            <span class="side-mark"><Icons.icon name="telescope" /></span>
            <span class="side-brand-text">
              <strong>{telescope_name(@telescope)}</strong>
              <span>{telescope_where(@telescope, @host)}</span>
            </span>
            <Icons.icon name="chevrons" class="icon switcher-chevrons" />
          </button>
          <div id="telescope-menu" popover class="switcher-menu">
            <p class="side-label">Telescopes</p>
            <ul :if={@telescopes != []} role="list">
              <li :for={t <- @telescopes}>
                <a href={~p"/telescope/#{t.id}?#{[return: @current_path || "/"]}"} class="side-link switcher-item" aria-current={@telescope && @telescope.id == t.id && "true"}>
                  <Icons.icon name={if t.simulated, do: "sim", else: "telescope"} />
                  <span class="switcher-name"><strong>{t.id}</strong><small>{telescope_where(t, @host)}<span :if={@alignments[t.id]}> · {@alignments[t.id].words}</span></small></span>
                  <AlignmentStatus.glyph :if={@alignments[t.id]} summary={@alignments[t.id]} size={18} class="switcher-al" />
                  <Icons.icon :if={@telescope && @telescope.id == t.id} name="check" class="icon switcher-check" />
                </a>
              </li>
            </ul>
            <p :if={@telescopes == []} class="switcher-empty">None connected. A telescope on this machine's USB, or on a box on this network, shows up here.</p>
            <a href={~p"/devices"} class="side-link"><Icons.icon name="plug" /><span>Devices</span></a>
          </div>
        </div>
        <%!-- how well the telescope you're driving is aligned: the same on every page, and it
              changes with the switcher --%>
        <AlignmentStatus.chip :if={@telescope} summary={@alignments[@telescope.id]} href={~p"/alignment/#{@telescope.id}"} />

        <%!-- a field-shaped key, so it reads as search; ⌘K opens the same thing --%>
        <button :if={@search != []} type="button" class="side-search" popovertarget="spotlight" phx-click={JS.push("reset", target: "#spotlight")}>
          <Icons.icon name="search" />
          <span>Search</span>
          <kbd aria-label="Command K">⌘K</kbd>
        </button>
        <.link :if={@search == []} navigate={~p"/search"} class="side-search">
          <Icons.icon name="search" />
          <span>Search</span>
        </.link>

        <ul role="list" class="side-top">
          <li>
            <.link navigate={~p"/"} class="side-link" aria-current={@current_path == "/" && "page"}>
              <Icons.icon name="house" />
              <span>Home</span>
            </.link>
          </li>
        </ul>
        <Controller.Components.Menu.menu variant="side" current={@current} />
        <%!-- night mode, the same switch on every page --%>
        <button :if={@search != []} type="button" class="side-link side-night" phx-click="night" phx-target="#spotlight" aria-pressed={to_string(@night == true)}>
          <span class="night-glyph" aria-hidden="true">◐</span><span>Night Mode</span><small>{if @night, do: "On", else: "Off"}</small>
        </button>
      </nav>
      <div class="shell-main">{render_slot(@inner_block)}</div>
      {render_slot(@search)}
    </div>
    """
  end

  defp telescope_name(nil), do: "No telescope"
  defp telescope_name(t), do: t.id

  # where it is, in the words a switcher needs: a box by name, or this machine
  defp telescope_where(nil, _host), do: "Connect one on Devices"
  defp telescope_where(%{simulated: true}, host), do: "Simulator on #{host}"
  defp telescope_where(%{where: nil}, host), do: "On #{host}"
  defp telescope_where(%{where: box}, _host), do: "On #{box}"

  # which machine this page is served from, by the name the cluster knows it
  # by (a box's Linux hostname stays the Nerves default, nerves-990c; the
  # network knows it as observatory, and so do the Mac's pages)
  defp host do
    case {node(), :inet.gethostname()} do
      {:nonode@nohost, {:ok, name}} -> name |> to_string() |> String.replace_suffix(".local", "")
      {:nonode@nohost, _} -> ""
      {n, _} -> Controller.Words.host(n)
    end
  end
end
