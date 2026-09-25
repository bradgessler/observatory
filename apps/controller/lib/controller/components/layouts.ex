defmodule Controller.Layouts do
  @moduledoc """
  This module holds layouts and related functionality
  used by your application.
  """
  use Controller, :html

  # Embed all files in layouts/* within this module.
  # The default root.html.heex file contains the HTML
  # skeleton of your application, namely HTML headers
  # and other static content.
  embed_templates "layouts/*"

  @doc """
  The layout every routed LiveView renders inside (see `Controller.live_view/0`).
  On a wide screen: the sidebar of every page, the current one marked, beside
  the page. On a phone the sidebar is not drawn; Home is the list, and each
  page's header links back to it.
  """
  def shell(assigns) do
    ~H"""
    <.frame current_path={assigns[:current_path]} night={assigns[:night]}>{@inner_content}</.frame>
    """
  end

  attr :current_path, :string, default: nil
  attr :night, :boolean, default: false
  slot :inner_block, required: true

  def frame(assigns) do
    assigns =
      assign(assigns,
        groups: Controller.Nav.groups(),
        current: Controller.Nav.current(assigns.current_path),
        host: host()
      )

    ~H"""
    <div class={["shell", @night && "night"]}>
      <nav class="sidebar" aria-label="Pages">
        <.link navigate={~p"/"} class="side-brand" aria-current={@current_path == "/" && "page"}>
          <strong>Observatory</strong>
          <span>{@host}</span>
        </.link>
        <div :for={{name, _blurb, items} <- @groups} class="side-group">
          <p class="side-label" id={"side-" <> slug(name)}>{name}</p>
          <ul role="list" aria-labelledby={"side-" <> slug(name)}>
            <li :for={{title, path, _sub, _doc} <- items}>
              <.link navigate={path} class="side-link" aria-current={@current == path && "page"}>{title}</.link>
            </li>
          </ul>
        </div>
      </nav>
      <div class="shell-main">{render_slot(@inner_block)}</div>
    </div>
    """
  end

  defp slug(name), do: name |> String.downcase() |> String.replace(~r/[^a-z0-9]+/, "-")

  # which machine this page is served from: the Mac, or a box by name
  defp host do
    case :inet.gethostname() do
      {:ok, name} -> name |> to_string() |> String.replace_suffix(".local", "")
      _ -> ""
    end
  end

  @doc """
  Renders your app layout.

  This function is typically invoked from every template,
  and it often contains your application menu, sidebar,
  or similar.

  ## Examples

      <Layouts.app flash={@flash}>
        <h1>Content</h1>
      </Layouts.app>

  """
  attr :flash, :map, required: true, doc: "the map of flash messages"

  attr :current_scope, :map,
    default: nil,
    doc: "the current [scope](https://hexdocs.pm/phoenix/scopes.html)"

  slot :inner_block, required: true

  def app(assigns) do
    ~H"""
    <header class="navbar px-4 sm:px-6 lg:px-8">
      <div class="flex-1">
        <a href="/" class="flex-1 flex w-fit items-center gap-2">
          <img src={~p"/images/logo.svg"} width="36" />
          <span class="text-sm font-semibold">v{Application.spec(:phoenix, :vsn)}</span>
        </a>
      </div>
      <div class="flex-none">
        <ul class="flex flex-column px-1 space-x-4 items-center">
          <li>
            <a href="https://phoenixframework.org/" class="btn btn-ghost">Website</a>
          </li>
          <li>
            <a href="https://github.com/phoenixframework/phoenix" class="btn btn-ghost">GitHub</a>
          </li>
          <li>
            <a href="https://hexdocs.pm/phoenix/overview.html" class="btn btn-primary">
              Get Started <span aria-hidden="true">&rarr;</span>
            </a>
          </li>
        </ul>
      </div>
    </header>

    <main class="px-4 py-20 sm:px-6 lg:px-8">
      <div class="mx-auto max-w-2xl space-y-4">
        {render_slot(@inner_block)}
      </div>
    </main>

    <.flash_group flash={@flash} />
    """
  end

  @doc """
  Shows the flash group with standard titles and content.

  ## Examples

      <.flash_group flash={@flash} />
  """
  attr :flash, :map, required: true, doc: "the map of flash messages"
  attr :id, :string, default: "flash-group", doc: "the optional id of flash container"

  def flash_group(assigns) do
    ~H"""
    <div id={@id} aria-live="polite">
      <.flash kind={:info} flash={@flash} />
      <.flash kind={:error} flash={@flash} />
    </div>
    """
  end
end
