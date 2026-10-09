defmodule Controller.Components.Menu do
  @moduledoc """
  Every page, grouped, drawn from `Controller.Nav`: the one list of pages
  there is. Two ways to draw it, the same entries in the same order:

    * `variant="side"`: the sidebar on a wide screen, a row per page, its
      icon and name, the page you're on filled and dotted;
    * `variant="list"`: Home on a phone or tablet (where there's no sidebar),
      a key per page, its name over what it's for.

  So a page is added in one place (`Controller.Nav`) and it's in the
  sidebar, on a phone's Home, and in Search.

      <.menu variant="side" current={@current} />
  """
  use Phoenix.Component

  alias Controller.Components.Icons

  attr :variant, :string, default: "side", values: ~w(side list)
  attr :current, :string, default: nil, doc: "the sidebar entry being shown (`Controller.Nav.current/1`), marked"
  attr :groups, :list, default: nil, doc: "defaults to `Controller.Nav.groups/0`"

  def menu(%{variant: "side"} = assigns) do
    assigns = assign(assigns, groups: assigns.groups || Controller.Nav.groups())

    ~H"""
    <div :for={{name, _blurb, pages} <- @groups} class="side-group">
      <p class="side-label" id={"side-" <> slug(name)}>{name}</p>
      <ul role="list" aria-labelledby={"side-" <> slug(name)}>
        <li :for={p <- pages}>
          <.link navigate={p.path} class="side-link" aria-current={@current == p.path && "page"}>
            <Icons.icon name={p.icon} />
            <span>{p.title}</span>
          </.link>
        </li>
      </ul>
    </div>
    """
  end

  def menu(%{variant: "list"} = assigns) do
    assigns = assign(assigns, groups: assigns.groups || Controller.Nav.groups())

    ~H"""
    <section :for={{name, blurb, pages} <- @groups} class="home-group" aria-labelledby={"home-" <> slug(name)}>
      <h2 id={"home-" <> slug(name)}>{name}</h2>
      <p class="dim">{blurb}</p>
      <ul class="home-list" role="list">
        <li :for={p <- pages} class="home-item">
          <.link navigate={p.path} class="home-btn">
            <Icons.icon name={p.icon} />
            <span class="home-btn-text">
              <strong>{p.title}</strong>
              <span>{p.line}</span>
            </span>
          </.link>
        </li>
      </ul>
    </section>
    """
  end

  defp slug(name), do: name |> String.downcase() |> String.replace(~r/[^a-z0-9]+/, "-")
end
