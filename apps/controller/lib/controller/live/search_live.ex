defmodule Controller.SearchLive do
  @moduledoc """
  Search as a page of its own, for where the popover can't open: a doc
  (a plain page, no LiveView behind it) links here, and so can a bookmark.
  The same finding as ⌘K (`Controller.Search`), as a list of rows.
  """
  use Controller, :live_view
  import Controller.Components.UI

  alias Controller.{Search, Settings}

  @impl true
  def mount(params, _session, socket) do
    q = params["q"] || ""
    {:ok, assign(socket, page_title: "Search", night: Settings.get("night", false), q: q, results: Search.find(q))}
  end

  @impl true
  def handle_event("search", %{"q" => q}, socket), do: {:noreply, assign(socket, q: q, results: Search.find(q))}

  def handle_event("stop", _, socket) do
    Controller.Stop.all()
    {:noreply, socket}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <.page id="search" night={@night}>
      <:header>
        <.back navigate={~p"/"} label="Home" section="Observatory" />
        <.title>Search</.title>
        <.actions search={false}><.stop /></.actions>
      </:header>

      <form class="search-page-form" role="search" phx-change="search" phx-submit="search">
        <input class="field" name="q" type="search" value={@q} autofocus autocomplete="off" placeholder="Search pages and help" aria-label="Search pages and help" phx-debounce="100" />
      </form>

      <.items label="results">
        <.link_item :for={r <- @results} navigate={r.path} label={r.title} detail={r.where} />
      </.items>
      <p :if={@results == []} class="hint" role="status">Nothing called that. Try part of a page's name, like "focus" or "site".</p>
    </.page>
    """
  end

end
