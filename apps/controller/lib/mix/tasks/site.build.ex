defmodule Mix.Tasks.Site.Build do
  @shortdoc "Build the static blog from posts/ into _site/"
  @moduledoc """
  The blog, as flat files: read `posts/*.md`, render with the same Markdown
  renderer the in-app docs use, and write `_site/` ready for GitHub Pages.

      mix site.build            # into _site
      mix site.build --out docs # somewhere else
      mix site.build --ogplus https://KEY.ogplus.net  # share images from OpenGraph+
      mix site.build --ogplus ""                       # share images from the hero pictures

  No Ruby, no Jekyll, no theme to fight: one index, one page per post, one
  stylesheet, and the post images copied across. Every page carries the Open
  Graph tags a link preview reads (Slack, iMessage, Discord, Mastodon, X).
  """
  use Mix.Task

  @out "_site"

  # Where bin/publish-blog puts it. Link previews need absolute URLs.
  @url "https://bradgessler.github.io/observatory-blog"

  # OpenGraph+ (https://opengraphplus.com) renders each page into its share
  # image: og:image is the site's connection URL followed by the page's path.
  # The connection URL is issued per site, so it comes from the OpenGraph+
  # dashboard (the bradgessler.github.io site, Meta Tags page) or from
  # `ogplus site connect bradgessler.github.io`, and goes here. While this is
  # nil a page shares with its hero picture instead.
  @ogplus nil

  @site_name "Observatory"
  @lede "Telescope control in Elixir: a mount driver, a Phoenix LiveView controller a phone opens, and a Nerves image for a Pi. Notes from building it."

  @impl true
  def run(args) do
    {opts, _, _} = OptionParser.parse(args, strict: [out: :string, ogplus: :string])
    out = opts[:out] || @out
    site = %{url: @url, ogplus: blank_to_nil(Keyword.get(opts, :ogplus, @ogplus))}
    root = File.cwd!()
    posts_dir = Path.join(root, "posts")

    paths = posts_dir |> Path.join("*.md") |> Path.wildcard()
    private!(paths)
    posts = paths |> Enum.map(&read_post/1) |> Enum.sort_by(& &1.date, {:desc, Date})

    File.rm_rf!(out)
    File.mkdir_p!(Path.join(out, "images"))

    case File.ls(Path.join(posts_dir, "images")) do
      {:ok, files} ->
        for f <- files, do: copy_image(Path.join([posts_dir, "images", f]), Path.join([out, "images", f]))

      _ ->
        :ok
    end

    File.write!(Path.join(out, "style.css"), css())
    File.write!(Path.join(out, "index.html"), index_page(posts, site))
    for p <- posts, do: File.write!(Path.join(out, p.slug <> ".html"), post_page(p, posts, site))
    # GitHub Pages runs Jekyll unless told not to; these are already built
    File.write!(Path.join(out, ".nojekyll"), "")

    Mix.shell().info("#{length(posts)} posts → #{out}/")
  end

  # -- where the telescope is stays home ---------------------------------------------------
  # The blog may say "the Bay Area", never the town: nothing that places the
  # site better than about 50 miles. The software keeps the real site; the
  # blog build refuses a post that names the configured town or gives its
  # latitude or longitude to a decimal (0.1° is about 7 miles), and strips
  # every image of its metadata (EXIF and GPS, XMP, comments) on the way out.

  # mix has loaded the config before any task runs
  defp private!(paths) do
    case Application.get_env(:controller, :site) do
      %{lat: lat, lon: lon} = site ->
        terms = private_terms(site[:name], lat, lon)

        for path <- paths, text = File.read!(path), term <- terms, String.contains?(String.downcase(text), String.downcase(term)) do
          Mix.raise("#{Path.basename(path)} gives away where the telescope is (\"#{term}\"). Say the Bay Area, not the town, and no coordinates to a decimal.")
        end

      _ ->
        :ok
    end
  end

  @doc false
  def private_terms(name, lat, lon) do
    coords = for v <- [lat, abs(lat), lon, abs(lon)], d <- [1, 2, 3], uniq: true, do: :erlang.float_to_binary(v / 1, decimals: d)
    Enum.reject([name | coords], &(&1 in [nil, ""]))
  end

  defp copy_image(from, to) do
    bytes = File.read!(from)

    stripped =
      case Path.extname(from) |> String.downcase() do
        e when e in [".jpg", ".jpeg"] -> strip_jpeg(bytes)
        ".png" -> strip_png(bytes)
        _ -> bytes
      end

    File.write!(to, stripped)
  end

  @doc "A JPEG without APP1–APP15 (EXIF with GPS, XMP, ICC, maker notes) or comments; the image data untouched."
  def strip_jpeg(<<0xFF, 0xD8, rest::binary>>), do: <<0xFF, 0xD8>> <> jpeg_segments(rest)
  def strip_jpeg(other), do: other

  # start of scan: everything from here is the picture itself
  defp jpeg_segments(<<0xFF, 0xDA, _::binary>> = scan), do: scan

  defp jpeg_segments(<<0xFF, m, len::16, rest::binary>>) when (m >= 0xE1 and m <= 0xEF) or m == 0xFE do
    n = len - 2
    <<_::binary-size(^n), tail::binary>> = rest
    jpeg_segments(tail)
  end

  defp jpeg_segments(<<0xFF, m, len::16, rest::binary>>) when m >= 0xC0 and m != 0xD8 and m != 0xD9 do
    n = len - 2
    <<body::binary-size(^n), tail::binary>> = rest
    <<0xFF, m, len::16, body::binary>> <> jpeg_segments(tail)
  end

  defp jpeg_segments(other), do: other

  @doc "A PNG without its text, EXIF and time chunks; the image chunks untouched."
  def strip_png(<<137, 80, 78, 71, 13, 10, 26, 10, rest::binary>>), do: <<137, 80, 78, 71, 13, 10, 26, 10>> <> png_chunks(rest)
  def strip_png(other), do: other

  defp png_chunks(<<len::32, type::binary-size(4), data::binary-size(len), crc::32, rest::binary>>) do
    kept = if type in ["tEXt", "zTXt", "iTXt", "eXIf", "tIME"], do: <<>>, else: <<len::32, type::binary, data::binary, crc::32>>
    kept <> png_chunks(rest)
  end

  defp png_chunks(rest), do: rest

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
      html: render(body)
    }
  end

  @doc """
  A post's markdown as HTML. The posts are ours, so raw HTML passes (an
  `<aside>` for the short version). Every image stands alone as a figure
  with its caption: the title in `![alt](src "caption")`, else the alt text,
  so a reader skimming the pictures gets the story from the captions. Tables
  scroll sideways on a phone instead of squashing.
  """
  def render(markdown) do
    markdown
    |> MDEx.to_html!(extension: [table: true, autolink: true, strikethrough: true], render: [unsafe: true])
    |> figures()
    |> String.replace("<table>", ~s(<div class="table-wrap"><table>))
    |> String.replace("</table>", "</table></div>")
  end

  defp figures(html) do
    Regex.replace(~r{<p><img src="([^"]+)" alt="([^"]*)"(?: title="([^"]*)")? />\s*</p>}, html, fn _, src, alt, title ->
      caption = if title != "", do: title, else: alt
      ~s(<figure><img src="#{src}" alt="#{alt}" loading="lazy" /><figcaption>#{caption}</figcaption></figure>)
    end)
  end

  # The picture that sells the post: `hero:` in the front matter if it is
  # there, otherwise the first image in the body, which is the one the author
  # led with.
  defp hero_image(meta, body) do
    case Regex.run(~r/!\[([^\]]*)\]\((images\/[^)\s]+)/, body) do
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

  defp index_page(posts, site) do
    # without OpenGraph+ the front page shares with the newest post's picture
    newest = List.first(posts) || %{hero: nil, hero_alt: ""}

    share = %{
      path: "",
      type: "website",
      title: @site_name,
      description: @lede,
      hero: newest.hero,
      hero_alt: newest.hero_alt,
      date: nil
    }

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

    layout(@site_name, share_tags(share, site), """
    <header class="site">
      <h1>#{@site_name}</h1>
      <p class="lede">#{esc(@lede)}</p>
      <p class="lede"><a href="https://github.com/bradgessler/observatory">Source on GitHub</a></p>
    </header>
    <ul class="posts">#{items}</ul>
    """, "wide")
  end

  defp post_page(post, all, site) do
    i = Enum.find_index(all, &(&1.slug == post.slug))
    # `all` is newest first, so the one before it in the list is the newer one
    newer = if i > 0, do: Enum.at(all, i - 1)
    older = Enum.at(all, i + 1)

    share = %{
      path: post.slug <> ".html",
      type: "article",
      title: post.title,
      description: post.summary,
      hero: post.hero,
      hero_alt: post.hero_alt,
      date: post.date
    }

    layout(post.title, share_tags(share, site) <> highlighting(), """
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

  # Code in colour, read the way an editor shows it: highlight.js from cdnjs,
  # the GitHub themes for dark and light. A page without it is still plain,
  # readable code.
  @hljs "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0"
  defp highlighting do
    """
    <link rel="stylesheet" media="(prefers-color-scheme: dark)" href="#{@hljs}/styles/github-dark.min.css" />
    <link rel="stylesheet" media="(prefers-color-scheme: light)" href="#{@hljs}/styles/github.min.css" />
    <script defer src="#{@hljs}/highlight.min.js"></script>
    <script defer src="#{@hljs}/languages/elixir.min.js"></script>
    <script>addEventListener("DOMContentLoaded", () => window.hljs && hljs.highlightAll());</script>
    """
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

  # What a link preview reads. og:image is OpenGraph+'s render of this very
  # page when it is set up (connection URL + the page's path on the host),
  # otherwise the page's hero picture; a page with neither gets a small card.
  defp share_tags(page, site) do
    url = "#{site.url}/#{page.path}"

    {image, image_alt} =
      cond do
        site.ogplus -> {String.trim_trailing(site.ogplus, "/") <> URI.parse(url).path, nil}
        page.hero -> {"#{site.url}/#{page.hero}", page.hero_alt}
        true -> {nil, nil}
      end

    [
      {"name", "description", page.description},
      {"property", "og:site_name", @site_name},
      {"property", "og:type", page.type},
      {"property", "og:title", page.title},
      {"property", "og:description", page.description},
      {"property", "og:url", url},
      {"property", "og:image", image},
      {"property", "og:image:alt", image_alt},
      {"property", "article:published_time", page.date && Date.to_iso8601(page.date)},
      {"name", "twitter:card", if(image, do: "summary_large_image", else: "summary")},
      # the article column is 46rem, so render the card at about that width
      {"property", "og:plus:viewport:width", site.ogplus && "800"}
    ]
    |> Enum.reject(fn {_, _, content} -> content in [nil, ""] end)
    |> Enum.map_join("\n", fn {attr, key, content} ->
      ~s(<meta #{attr}="#{key}" content="#{esc(content)}" />)
    end)
  end

  defp layout(title, head, inner, class \\ "") do
    """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>#{esc(title)} · #{@site_name}</title>
    #{head}
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

  defp blank_to_nil(""), do: nil
  defp blank_to_nil(s), do: s

  # safe in text and inside a double-quoted attribute
  defp esc(s) do
    s
    |> to_string()
    |> String.replace("&", "&amp;")
    |> String.replace("<", "&lt;")
    |> String.replace(">", "&gt;")
    |> String.replace(~s("), "&quot;")
  end

  # The same idea as the app: dark ground, one accent, generous measure.
  defp css do
    """
    :root { color-scheme: dark light; --bg:#0b0d12; --panel:#12151c; --line:#232834; --text:#e6e8ee; --dim:#8f95a8; --accent:#6ea8ff; }
    @media (prefers-color-scheme: light) { :root { --bg:#f7f8fa; --panel:#fff; --line:#e1e4ea; --text:#14171d; --dim:#5a6372; --accent:#2457d6; } }
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
    article figure { margin:2rem 0; }
    article figure img { margin:0 auto; }
    article figcaption { color:var(--dim); font-size:.9rem; line-height:1.45; margin-top:.6rem; text-align:center; text-wrap:balance; }
    article h2 { font-size:1.35rem; margin-top:3rem; text-wrap:balance; }
    article h3 { font-size:1.05rem; margin:2rem 0 .4rem; }
    article pre { background:var(--panel); padding:1rem 1.1rem; border-radius:10px; overflow-x:auto; font-size:.85rem; line-height:1.5; }
    article pre code.hljs { background:transparent; padding:0; }
    article code { font-size:.9em; }
    article :not(pre) > code { background:var(--panel); padding:.1em .35em; border-radius:5px; }
    article pre code { font-size:inherit; }
    article aside { background:var(--panel); border-left:3px solid var(--accent); border-radius:10px; padding:1rem 1.25rem; margin:1.75rem 0; }
    article aside > :first-child { margin-top:0; }
    article aside > :last-child { margin-bottom:0; }
    .table-wrap { overflow-x:auto; margin:1.5rem 0; border-radius:10px; border:1px solid var(--line); }
    article table { width:100%; border-collapse:collapse; font-size:.92rem; font-variant-numeric:tabular-nums; }
    article th, article td { text-align:left; vertical-align:top; padding:.6rem .8rem; border-bottom:1px solid var(--line); }
    article thead th { background:var(--panel); color:var(--dim); font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
    article tbody tr:last-child td { border-bottom:0; }
    article blockquote { border-left:3px solid var(--dim); margin:1.5rem 0; padding-left:1rem; color:var(--dim); }
    header.site { border-bottom:1px solid var(--panel); padding-bottom:1.5rem; }
    /* OpenGraph+ sets data-ogplus while it photographs a page for its share card */
    html[data-ogplus] .back { display:none; }
    """
  end
end
