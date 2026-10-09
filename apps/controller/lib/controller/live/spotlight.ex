defmodule Controller.Spotlight do
  @moduledoc """
  Search, over every page: type a bit of a page's name, arrow to it, Enter.
  `Controller.Search` does the finding; this is the box and the list.

  It's a native popover (`id="spotlight"`), so opening, closing (Escape, a
  tap outside) and focusing the field take no script: any button with
  `popovertarget="spotlight"` opens it (the sidebar's Search on a wide
  screen, the search key in a phone's header), and ⌘K or Ctrl-K does too
  (`app.js`, the one part a browser keeps to itself). Rendered once per
  page by the layout, inside the shell, so night mode reaches it.

  Opened with nothing typed, it lists this page's help first and then every
  page, so on a phone it's also the menu.
  """
  use Controller, :live_component

  alias Controller.Components.Icons
  alias Controller.Search

  @impl true
  def mount(socket), do: {:ok, assign(socket, q: "", active: 0, results: nil)}

  # the layout hands this the page's path on every render of the page (a new
  # frame on a camera page, once a second): only a new page changes the list
  @impl true
  def update(assigns, socket) do
    here = assigns[:here]

    if socket.assigns.results && socket.assigns[:here] == here do
      {:ok, socket}
    else
      {:ok, assign(socket, here: here, results: Search.find(socket.assigns.q, here: here))}
    end
  end

  @impl true
  def handle_event("search", %{"q" => q}, socket) do
    {:noreply, assign(socket, q: q, active: 0, results: Search.find(q, here: socket.assigns.here))}
  end

  # opened again: a fresh start
  def handle_event("reset", _, socket), do: handle_event("search", %{"q" => ""}, socket)

  def handle_event("key", %{"key" => key}, socket) when key in ["ArrowDown", "ArrowUp"] do
    n = length(socket.assigns.results)
    step = if key == "ArrowDown", do: 1, else: -1
    {:noreply, assign(socket, active: if(n == 0, do: 0, else: Integer.mod(socket.assigns.active + step, n)))}
  end

  def handle_event("key", _, socket), do: {:noreply, socket}

  # night mode, from the sidebar or the search sheet: one setting, every page turns red with it
  def handle_event("night", _, socket) do
    Controller.Settings.put("night", !Controller.Settings.get("night", false))
    {:noreply, socket}
  end

  def handle_event("go", _, socket) do
    case Enum.at(socket.assigns.results, socket.assigns.active) do
      nil -> {:noreply, socket}
      %{kind: :doc, path: path} -> {:noreply, redirect(socket, to: path)}
      %{path: path} -> {:noreply, push_navigate(socket, to: path)}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div id="spotlight" popover class="spotlight" role="dialog" aria-modal="true" aria-label="Search">
      <form class="spotlight-form" role="search" phx-change="search" phx-submit="go" phx-target={@myself}>
        <Icons.icon name="search" class="icon spotlight-glass" />
        <input
          id="spotlight-input"
          name="q"
          type="search"
          value={@q}
          autofocus
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          enterkeyhint="go"
          placeholder="Search pages and help"
          aria-label="Search pages and help"
          role="combobox"
          aria-expanded="true"
          aria-controls="spotlight-results"
          aria-activedescendant={@results != [] && "spotlight-#{@active}"}
          phx-keydown="key"
          phx-target={@myself}
          phx-debounce="0"
        />
        <button type="button" class="spotlight-close" popovertarget="spotlight" popovertargetaction="hide" aria-label="Close search">
          <Icons.icon name="close" />
        </button>
      </form>
      <%!-- nothing typed: the one switch every page shares, first --%>
      <button :if={@q == ""} type="button" class="spotlight-item spotlight-night" phx-click="night" phx-target={@myself} aria-pressed={to_string(Controller.Settings.get("night", false))}>
        <span class="night-glyph" aria-hidden="true">◐</span>
        <span class="spotlight-text"><strong>Night Mode</strong><small>{if Controller.Settings.get("night", false), do: "On: everything red", else: "Off"}</small></span>
      </button>
      <ul id="spotlight-results" class="spotlight-results" role="listbox" aria-label="Results">
        <li :for={{r, i} <- Enum.with_index(@results)}>
          <.link
            id={"spotlight-#{i}"}
            role="option"
            aria-selected={to_string(i == @active)}
            class="spotlight-item"
            navigate={if r.kind == :page, do: r.path}
            href={if r.kind == :doc, do: r.path}
          >
            <Icons.icon name={r.icon} />
            <span class="spotlight-text">
              <strong>{r.title}</strong>
              <small>{detail(r)}</small>
            </span>
          </.link>
        </li>
      </ul>
      <p :if={@results == []} class="spotlight-none" role="status">Nothing called that. Try part of a page's name, like "focus" or "site".</p>
      <p class="spotlight-keys" aria-hidden="true">↑ ↓ to pick · Enter to go · Esc to close</p>
    </div>
    """
  end

  defp detail(%{kind: :doc, where: "About this page"}), do: "About this page"
  defp detail(%{kind: :doc}), do: "Help"
  defp detail(%{where: where}), do: where
end
