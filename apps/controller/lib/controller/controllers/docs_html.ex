defmodule Controller.DocsHTML do
  use Controller, :html

  def show(assigns) do
    ~H"""
    <main class={["doc", @night && "night"]}>
      <header>
        <a href="javascript:history.back()" class="ghost">‹ back</a>
        <nav class="doc-nav" aria-label="other docs">
          <.link href={~p"/docs/keypad"} class="help" aria-current={@title == "Keypad" && "page"}>keypad</.link>
          <.link href={~p"/docs/sky"} class="help" aria-current={@title == "Sky" && "page"}>sky</.link>
          <.link href={~p"/docs/horizon"} class="help" aria-current={@title == "Horizon" && "page"}>horizon</.link>
          <.link href={~p"/docs/magnitude"} class="help" aria-current={@title == "Magnitude" && "page"}>magnitude</.link>
        </nav>
      </header>
      <span id="content" tabindex="-1" class="skip-target"></span>
      <article>{Phoenix.HTML.raw(@html)}</article>
    </main>
    """
  end
end
