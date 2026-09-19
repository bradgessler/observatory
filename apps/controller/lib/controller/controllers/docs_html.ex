defmodule Controller.DocsHTML do
  use Controller, :html

  def show(assigns) do
    ~H"""
    <main class={["doc", @night && "night"]}>
      <header>
        <a href="javascript:history.back()" class="ghost">‹ back</a>
        <nav class="doc-nav">
          <.link href={~p"/docs/keypad"} class="help">keypad</.link>
          <.link href={~p"/docs/sky"} class="help">sky</.link>
          <.link href={~p"/docs/horizon"} class="help">horizon</.link>
          <.link href={~p"/docs/magnitude"} class="help">magnitude</.link>
        </nav>
      </header>
      <article>{Phoenix.HTML.raw(@html)}</article>
    </main>
    """
  end
end
