defmodule Controller.DocsController do
  @moduledoc """
  Markdown pages from `priv/docs/*.md`, rendered with MDEx. The UI links here
  with a small "?" instead of carrying paragraphs of explanation. Swappable
  for sitepress-ex later; the files stay the same.
  """
  use Controller, :controller

  @dir :code.priv_dir(:controller) |> Path.join("docs")

  def show(conn, %{"slug" => slug}) do
    with true <- slug =~ ~r/^[a-z0-9-]+$/,
         path = Path.join(@dir, slug <> ".md"),
         {:ok, md} <- File.read(path) do
      html = MDEx.to_html!(md, extension: [table: true, autolink: true], render: [unsafe: false])
      title = md |> String.split("\n", parts: 2) |> hd() |> String.trim_leading("# ")

      conn
      |> assign(:page_title, title)
      |> render(:show, title: title, html: html, night: Controller.Settings.get("night", false))
    else
      _ -> conn |> put_status(:not_found) |> text("no such page")
    end
  end
end
