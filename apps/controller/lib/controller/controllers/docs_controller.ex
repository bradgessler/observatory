defmodule Controller.DocsController do
  @moduledoc """
  Markdown pages from `priv/docs/*.md`, rendered with MDEx. The UI links here
  with a small "?" instead of carrying paragraphs of explanation. Swappable
  for sitepress-ex later; the files stay the same.
  """
  use Controller, :controller

  # at runtime: a module attribute would bake in the build machine's path,
  # which on a box points nowhere (so a box drew no stars and served no docs)
  defp dir, do: :code.priv_dir(:controller) |> Path.join("docs")

  def show(conn, %{"slug" => slug}) do
    with true <- slug =~ ~r/^[a-z0-9-]+$/,
         path = Path.join(dir(), slug <> ".md"),
         {:ok, md} <- File.read(path) do
      # header ids: a hint can link straight to the section that explains it
      # the first line ("# Title") is the toolbar's title; the page has one h1
      body = md |> String.split("\n", parts: 2) |> List.last()
      html = MDEx.to_html!(body, extension: [table: true, autolink: true, header_id_prefix: ""], render: [unsafe: false])
      title = md |> String.split("\n", parts: 2) |> hd() |> String.trim_leading("# ")

      conn
      |> assign(:page_title, title)
      |> render(:show, title: title, slug: slug, html: html, night: Controller.Settings.get("night", false))
    else
      _ -> conn |> put_status(:not_found) |> text("no such page")
    end
  end
end
