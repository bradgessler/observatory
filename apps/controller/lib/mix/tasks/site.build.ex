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

    {hero, hero_alt} = hero_image(meta, body)

    %{
      slug: slug,
      title: meta["title"] || slug,
      summary: meta["summary"] || "",
      date: parse_date(meta["date"], slug),
      hero: hero,
      hero_alt: hero_alt,
      html: MDEx.to_html!(body, extension: [table: true, autolink: true], render: [unsafe: false])
    }
  end

  # The picture that sells the post: `hero:` in the front matter if it is
  # there, otherwise the first image in the body, which is the one the author
  # led with.
  defp hero_image(meta, body) do
    case Regex.run(~r/!\[([^\]]*)\]\((images\/[^)]+)\)/, body) do
      [_, alt, src] -> {meta["hero"] || src, meta["hero_alt"] || alt}
      _ -> {meta["hero"], meta["hero_alt"] || ""}
    end
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
        <li class="card">
          <a href="#{p.slug}.html">
            #{hero_tag(p)}
            <div class="card-body">
              <h2>#{esc(p.title)}</h2>
              <time datetime="#{p.date}">#{pretty(p.date)}</time>
              <p>#{esc(p.summary)}</p>
            </div>
          </a>
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
    """, "wide")
  end

  defp post_page(post, all) do
    i = Enum.find_index(all, &(&1.slug == post.slug))
    # `all` is newest first, so the one before it in the list is the newer one
    newer = if i > 0, do: Enum.at(all, i - 1)
    older = Enum.at(all, i + 1)

    layout(post.title, """
    <p class="back"><a href="index.html">‹ Observatory</a></p>
    <article>
      <h1>#{esc(post.title)}</h1>
      <time datetime="#{post.date}">#{pretty(post.date)}</time>
      #{post.html}
    </article>
    <nav class="prevnext">
      #{nav_link(older, "Earlier")}
      #{nav_link(newer, "Later")}
    </nav>
    """)
  end

  defp nav_link(nil, _), do: ~s(<span></span>)

  defp nav_link(p, label) do
    """
    <a href="#{p.slug}.html" class="#{String.downcase(label)}">
      <span class="dir">#{label}</span>
      <strong>#{esc(p.title)}</strong>
    </a>
    """
  end

  defp hero_tag(%{hero: nil}), do: ""
  defp hero_tag(%{hero: src, hero_alt: alt}), do: ~s(<img src="#{src}" alt="#{esc(alt)}" loading="lazy" />)

  defp layout(title, inner), do: layout(title, inner, "")

  defp layout(title, inner, class) do
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
    <main class="#{class}">
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
    main.wide { max-width: 68rem; }
    main.wide header.site { max-width: 46rem; }
    a { color: var(--accent); }
    h1 { font-size: 2rem; line-height:1.2; margin: 0 0 .5rem; }
    h2 { font-size: 1.25rem; margin: 2.5rem 0 .5rem; }
    time { color: var(--dim); font-size: .9rem; }
    .lede { color: var(--dim); }
    .back a { color: var(--dim); text-decoration: none; }
    ul.posts { list-style:none; padding:0; display:grid; gap:1.75rem; margin-top:2.5rem; grid-template-columns:repeat(auto-fit,minmax(20rem,1fr)); }
    .card { background:var(--panel); border-radius:16px; overflow:hidden; transition:transform .12s ease; }
    .card:hover { transform:translateY(-2px); }
    .card a { text-decoration:none; color:inherit; display:block; }
    .card img { width:100%; aspect-ratio:16/10; object-fit:cover; object-position:center; display:block; margin:0; border-radius:0; background:#000; }
    .card-body { padding:1.1rem 1.35rem 1.4rem; }
    .card h2 { font-size:1.2rem; margin:0 0 .15rem; color:var(--accent); }
    .card p { color:var(--dim); margin:.5rem 0 0; font-size:.95rem; }
    nav.prevnext { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-top:4rem; padding-top:2rem; border-top:1px solid var(--panel); }
    nav.prevnext a { background:var(--panel); border-radius:12px; padding:1rem 1.15rem; text-decoration:none; color:inherit; }
    nav.prevnext .later { text-align:right; }
    nav.prevnext .dir { display:block; color:var(--dim); font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; margin-bottom:.2rem; }
    nav.prevnext strong { color:var(--accent); font-weight:600; }
    @media (max-width:32rem) { nav.prevnext { grid-template-columns:1fr; } nav.prevnext .later { text-align:left; } }
    article img { max-width:100%; height:auto; border-radius:12px; display:block; margin:1.5rem auto; }
    article pre { background:var(--panel); padding:1rem; border-radius:10px; overflow-x:auto; font-size:.85rem; }
    article code { font-size:.9em; }
    article pre code { font-size:inherit; }
    article blockquote { border-left:3px solid var(--dim); margin:1.5rem 0; padding-left:1rem; color:var(--dim); }
    header.site { border-bottom:1px solid var(--panel); padding-bottom:1.5rem; }
    """
  end
end
