defmodule Controller.DocsHTML do
  use Controller, :html

  def show(assigns) do
    ~H"""
    <Controller.Layouts.frame night={@night}>
    <main class={["doc", @night && "night"]}>
      <%!-- the same toolbar as every page; STOP is a form here, this page has no LiveView --%>
      <header class="page-header">
        <.link navigate={~p"/"} class="tb-lead tb-home" aria-label="Home"><Controller.Components.Icons.icon name="house" /></.link>
        <span class="tb-over">Help</span>
        <h1 class="page-title">{@title}</h1>
        <span class="actions">
          <.link navigate={~p"/search"} class="search-key" aria-label="Search"><Controller.Components.Icons.icon name="search" /></.link>
          <.form for={%{}} action={~p"/stop"} method="post" class="stop-form">
            <button type="submit" class="stop-mini" aria-label="stop the mount">STOP</button>
          </.form>
        </span>
      </header>
      <div class="doc-head">
        <nav class="doc-nav" aria-label="other docs">
          <.link href={~p"/docs/keypad"} class="help" aria-current={@slug == "keypad" && "page"}>Keypad</.link>
          <.link href={~p"/docs/sky"} class="help" aria-current={@slug == "sky" && "page"}>Sky Map</.link>
          <.link href={~p"/docs/horizon"} class="help" aria-current={@slug == "horizon" && "page"}>Horizon</.link>
          <.link href={~p"/docs/magnitude"} class="help" aria-current={@slug == "magnitude" && "page"}>Magnitude</.link>
          <.link href={~p"/docs/glossary"} class="help" aria-current={@slug == "glossary" && "page"}>Words</.link>
        </nav>
      </div>
      <span id="content" tabindex="-1" class="skip-target"></span>
      <article>{Phoenix.HTML.raw(@html)}</article>
    </main>
    </Controller.Layouts.frame>
    """
  end
end
