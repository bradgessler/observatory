defmodule Mix.Tasks.Site.Build do
  @shortdoc "Build the static blog from posts/ into _site/"
  @moduledoc """
  The blog, as flat files: read `posts/*.md`, render with the same Markdown
  renderer the in-app docs use, and write `_site/` ready for GitHub Pages.

      mix site.build            # into _site
      mix site.build --out docs # somewhere else

  No Ruby, no Jekyll, no theme to fight: one index, one page per post, one
  stylesheet, and the post images copied across.
  """
  use Mix.Task

  @out "_site"

  @impl true
  def run(args) do
    {opts, _, _} = OptionParser.parse(args, strict: [out: :string])
    out = opts[:out] || @out
    root = File.cwd!()
    posts_dir = Path.join(root, "posts")

    posts =
      posts_dir
      |> Path.join("*.md")
      |> Path.wildcard()
      |> Enum.map(&read_post/1)
      |> Enum.sort_by(& &1.date, {:desc, Date})

    File.rm_rf!(out)
    File.mkdir_p!(Path.join(out, "images"))

    case File.ls(Path.join(posts_dir, "images")) do
      {:ok, files} ->
        for f <- files, do: File.cp!(Path.join([posts_dir, "images", f]), Path.join([out, "images", f]))

      _ ->
        :ok
    end

    File.write!(Path.join(out, "style.css"), css())
    File.write!(Path.join(out, "index.html"), index_page(posts))
    for p <- posts, do: File.write!(Path.join(out, p.slug <> ".html"), post_page(p, posts))
    # GitHub Pages runs Jekyll unless told not to; these are already built
    File.write!(Path.join(out, ".nojekyll"), "")

    Mix.shell().info("#{length(posts)} posts → #{out}/")
  end

  defp read_post(path) do
    raw = File.read!(path)
    {meta, body} = split_front_matter(raw)
    slug = path |> Path.basename(".md")

    %{
      slug: slug,
      title: meta["title"] || slug,
      summary: meta["summary"] || "",
      date: parse_date(meta["date"], slug),
      html: MDEx.to_html!(body, extension: [table: true, autolink: true], render: [unsafe: false])
    }
  end

  # A tiny front-matter reader: key: value, quotes optional. The posts are ours.
  defp split_front_matter("---\n" <> rest) do
    case String.split(rest, "\n---", parts: 2) do
      [head, body] ->
        meta =
          head
          |> String.split("\n", trim: true)
          |> Enum.reduce(%{}, fn line, acc ->
            case String.split(line, ":", parts: 2) do
              [k, v] -> Map.put(acc, String.trim(k), v |> String.trim() |> String.trim(~s(")))
              _ -> acc
            end
          end)

        {meta, String.trim_leading(body, "-\n")}

      _ ->
        {%{}, rest}
    end
  end

  defp split_front_matter(raw), do: {%{}, raw}

  defp parse_date(str, slug) do
    with s when is_binary(s) <- str, {:ok, d} <- Date.from_iso8601(String.slice(s, 0, 10)) do
      d
    else
      _ ->
        case Regex.run(~r/^(\d{4})-(\d{2})-(\d{2})/, slug) do
          [_, y, m, d] -> Date.new!(String.to_integer(y), String.to_integer(m), String.to_integer(d))
          _ -> ~D[2026-01-01]
        end
    end
  end

  # -- pages ---------------------------------------------------------------------------

  defp index_page(posts) do
    items =
      Enum.map_join(posts, "\n", fn p ->
        """
        <li>
          <a href="#{p.slug}.html"><strong>#{esc(p.title)}</strong></a>
          <time datetime="#{p.date}">#{pretty(p.date)}</time>
          <p>#{esc(p.summary)}</p>
        </li>
        """
      end)

    layout("Observatory", """
    <header class="site">
      <h1>Observatory</h1>
      <p class="lede">
        Telescope control in Elixir: a mount driver, a Phoenix LiveView controller a phone opens,
        and a Nerves image for a Pi. Notes from building it.
      </p>
      <p class="lede"><a href="https://github.com/bradgessler/observatory">Source on GitHub</a></p>
    </header>
    <ul class="posts">#{items}</ul>
    """)
  end

  defp post_page(post, _all) do
    layout(post.title, """
    <p class="back"><a href="index.html">‹ Observatory</a></p>
    <article>
      <h1>#{esc(post.title)}</h1>
      <time datetime="#{post.date}">#{pretty(post.date)}</time>
      #{post.html}
    </article>
    """)
  end

  defp layout(title, inner) do
    """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>#{esc(title)} · Observatory</title>
    <link rel="stylesheet" href="style.css" />
    </head>
    <body>
    <main>
    #{inner}
    </main>
    </body>
    </html>
    """
  end

  defp pretty(d), do: "#{Calendar.strftime(d, "%-d %B %Y")}"

  defp esc(s) do
    s
    |> to_string()
    |> String.replace("&", "&amp;")
    |> String.replace("<", "&lt;")
    |> String.replace(">", "&gt;")
  end

  # The same idea as the app: dark ground, one accent, generous measure.
  defp css do
    """
    :root { color-scheme: dark light; --bg:#0b0d12; --panel:#12151c; --text:#e6e8ee; --dim:#8f95a8; --accent:#6ea8ff; }
    @media (prefers-color-scheme: light) { :root { --bg:#f7f8fa; --panel:#fff; --text:#14171d; --dim:#5a6372; --accent:#2457d6; } }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:17px/1.6 -apple-system, system-ui, sans-serif; }
    main { max-width: 46rem; margin: 0 auto; padding: 3rem 1.25rem 6rem; }
    a { color: var(--accent); }
    h1 { font-size: 2rem; line-height:1.2; margin: 0 0 .5rem; }
    h2 { font-size: 1.25rem; margin: 2.5rem 0 .5rem; }
    time { color: var(--dim); font-size: .9rem; }
    .lede { color: var(--dim); }
    .back a { color: var(--dim); text-decoration: none; }
    ul.posts { list-style:none; padding:0; display:grid; gap:1.5rem; margin-top:2.5rem; }
    ul.posts li { background:var(--panel); border-radius:14px; padding:1.25rem 1.5rem; }
    ul.posts strong { font-size:1.15rem; }
    ul.posts p { color:var(--dim); margin:.35rem 0 0; }
    ul.posts a { text-decoration:none; }
    article img { max-width:100%; height:auto; border-radius:12px; display:block; margin:1.5rem auto; }
    article pre { background:var(--panel); padding:1rem; border-radius:10px; overflow-x:auto; font-size:.85rem; }
    article code { font-size:.9em; }
    article pre code { font-size:inherit; }
    article blockquote { border-left:3px solid var(--dim); margin:1.5rem 0; padding-left:1rem; color:var(--dim); }
    header.site { border-bottom:1px solid var(--panel); padding-bottom:1.5rem; }
    """
  end
end
