defmodule Mix.Tasks.Site.Build do
  @shortdoc "Build the static blog from posts/ and observations/ into _site/"
  @moduledoc """
  The blog, as flat files: read `posts/*.md`, render with the same Markdown
  renderer the in-app docs use, and write `_site/` ready for GitHub Pages.

  Observations are the pictures, a folder per night under `observations/`:

      observations/2026-10-03/session.md     title, date, summary, then one line per fact about the night
                                             (Location, Telescope, Camera, ...) and a few words underneath
      observations/2026-10-03/objects.json   one entry per picture: what it is, the facts, how it was made
      observations/2026-10-03/images/        <slug>.jpg, <slug>-1600.jpg, <slug>-thumb.jpg, <slug>-labels.jpg
                                             and, for a mosaic, <slug>-frames.jpg

  A night's page is its pictures on black; each opens a page with the plain
  picture first, then the labelled one with the facts, then the part for
  photographers. Each of those pages carries its own share card, a
  `<template id="ogplus">` that OpenGraph+ photographs in place of the page.

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
  # The connection URL is issued per site (`ogplus site create
  # bradgessler.github.io` made this one, 4 October 2026) and is public: it is
  # in every page's og:image. Set to nil, or built with `--ogplus ""`, a page
  # shares with its hero picture instead.
  @ogplus "https://mlghbepw.ogplus.net"

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
    nights = Path.wildcard(Path.join([root, "observations", "*", "session.md"]))
    private!(paths ++ nights ++ Path.wildcard(Path.join([root, "observations", "*", "objects.json"])))
    posts = paths |> Enum.map(&read_post/1) |> Enum.sort_by(& &1.date, {:desc, Date})
    sessions = nights |> Enum.map(&read_session/1) |> Enum.sort_by(& &1.date, {:desc, Date})

    File.rm_rf!(out)
    File.mkdir_p!(Path.join(out, "images"))

    case File.ls(Path.join(posts_dir, "images")) do
      {:ok, files} ->
        for f <- files, do: copy_image(Path.join([posts_dir, "images", f]), Path.join([out, "images", f]))

      _ ->
        :ok
    end

    File.write!(Path.join(out, "style.css"), css())
    File.write!(Path.join(out, "index.html"), index_page(posts, sessions, site))
    for p <- posts, do: File.write!(Path.join(out, p.slug <> ".html"), post_page(p, posts, site))
    write_observations(sessions, out, site)
    # GitHub Pages runs Jekyll unless told not to; these are already built
    File.write!(Path.join(out, ".nojekyll"), "")

    Mix.shell().info("#{length(posts)} posts, #{length(sessions)} observing nights → #{out}/")
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
          Mix.raise("#{Path.relative_to_cwd(path)} gives away where the telescope is (\"#{term}\"). Say the Bay Area, not the town, and no coordinates to a decimal.")
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
      html: body |> render() |> from_root()
    }
  end

  # A post links to a night as the repository lays it out, from posts/ up to
  # observations/ (so the link works on GitHub too); on the site the post sits
  # at the root, beside observations/.
  defp from_root(html), do: String.replace(html, ~s(href="../observations/), ~s(href="observations/))

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

  defp index_page(posts, sessions, site) do
    # without OpenGraph+ the front page shares with the newest post's picture
    newest = List.first(posts) || %{hero: nil, hero_alt: ""}

    card =
      case {sessions, posts} do
        {[night | _], _} -> collage_card(@site_name, @lede, night, "observations/#{night.slug}/")
        {_, [post | _]} -> post_card(%{post | title: @site_name, summary: @lede})
        _ -> nil
      end

    share = %{
      path: "",
      type: "website",
      title: @site_name,
      description: @lede,
      hero: newest.hero,
      hero_alt: newest.hero_alt,
      date: nil,
      card: card
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
    #{card && "<template id=\"ogplus\">#{card}</template>"}
    <header class="site">
      <h1>#{@site_name}</h1>
      <p class="lede">#{esc(@lede)}</p>
      <p class="lede"><a href="https://github.com/bradgessler/observatory">Source on GitHub</a></p>
    </header>
    #{latest_night(sessions)}
    <ul class="posts">#{items}</ul>
    """, "wide")
  end

  # The newest night's pictures, on black, above the posts.
  defp latest_night([]), do: ""

  defp latest_night([night | _]) do
    """
    <a class="night" href="observations/">
      <div class="strip">#{strip(night, "observations/#{night.slug}/")}</div>
      <div class="card-body">
        <h2>Observations</h2>
        <p>Pictures from the telescope, a page per night. Latest: #{esc(night.title)}, #{count(night.objects)}.</p>
      </div>
    </a>
    """
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
      date: post.date,
      card: post_card(post)
    }

    layout(post.title, share_tags(share, site) <> highlighting(), """
    <template id="ogplus">#{share.card}</template>
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

  # -- observations ----------------------------------------------------------------------
  # A night is a folder: session.md says where, with what and under what sky;
  # objects.json holds each picture's words. The pictures arrive finished and
  # at every size the pages use; the build only strips their metadata.

  defp read_session(path) do
    dir = Path.dirname(path)
    raw = File.read!(path)
    {meta, body} = split_front_matter(raw)
    slug = Path.basename(dir)

    data =
      case File.read(Path.join(dir, "objects.json")) do
        {:ok, json} -> Jason.decode!(json)
        _ -> %{}
      end

    %{
      slug: slug,
      dir: dir,
      title: meta["title"] || slug,
      summary: meta["summary"] || "",
      date: parse_date(meta["date"], slug),
      rows: spec_rows(raw),
      html: render(body),
      objects: data["objects"] || [],
      credit: data["credit"],
      made_with: data["made_with"]
    }
  end

  # The night's facts, in the order the file gives them: every front-matter
  # line that is not the title, date or summary, its key as the label.
  defp spec_rows("---\n" <> rest) do
    [head | _] = String.split(rest, "\n---", parts: 2)

    for line <- String.split(head, "\n", trim: true),
        [k, v] <- [String.split(line, ":", parts: 2)],
        k = String.trim(k),
        k not in ["title", "date", "summary"],
        do: {k, v |> String.trim() |> String.trim(~s("))}
  end

  defp spec_rows(_), do: []

  defp write_observations([], _out, _site), do: :ok

  defp write_observations(sessions, out, site) do
    File.mkdir_p!(Path.join(out, "observations"))
    File.write!(Path.join([out, "observations", "index.html"]), observations_page(sessions, site))

    for night <- sessions do
      to = Path.join([out, "observations", night.slug])
      File.mkdir_p!(Path.join(to, "images"))

      case File.ls(Path.join(night.dir, "images")) do
        {:ok, files} -> for f <- files, do: copy_image(Path.join([night.dir, "images", f]), Path.join([to, "images", f]))
        _ -> :ok
      end

      File.write!(Path.join(to, "index.html"), session_page(night, site))
      for o <- night.objects, do: File.write!(Path.join(to, o["slug"] <> ".html"), object_page(night, o, site))
    end
  end

  defp observations_page(sessions, site) do
    newest = hd(sessions)
    lede = "Pictures from the telescope, a page per night."
    card = collage_card("Observations", lede, newest, newest.slug <> "/")
    share = %{path: "observations/", type: "website", title: "Observations", description: lede, hero: cover(newest), hero_alt: cover_alt(newest), date: nil, card: card}

    nights =
      Enum.map_join(sessions, "\n", fn night ->
        """
        <li>
          <a class="night" href="#{night.slug}/">
            <div class="strip">#{strip(night, night.slug <> "/")}</div>
            <div class="card-body">
              <h2>#{esc(night.title)}</h2>
              <p>#{esc(night.summary)}</p>
            </div>
          </a>
        </li>
        """
      end)

    layout("Observations", share_tags(share, site), """
    <template id="ogplus">#{card}</template>
    <p class="back"><a href="../index.html">‹ Observatory</a></p>
    <header>
      <h1>Observations</h1>
      <p class="lede">#{lede}</p>
    </header>
    <ul class="nights">#{nights}</ul>
    #{rights(newest.date.year)}
    """, "wide", "../", "obs")
  end

  # The pictures and the words about them are Brad's (COPYRIGHT.md); every page of them says so.
  defp rights(year), do: ~s(<p class="rights">© #{year} Brad Gessler. The pictures and the words are his own; all rights reserved.</p>)

  # Four of a night's pictures side by side, for a link to that night.
  defp strip(night, prefix) do
    night.objects
    |> Enum.take(4)
    |> Enum.map_join("\n", &~s(<img src="#{prefix}images/#{&1["slug"]}-thumb.jpg" alt="#{esc(&1["title"])}" loading="lazy" />))
  end

  defp session_page(night, site) do
    card = collage_card(night.title, night.summary, night, "")
    share = %{path: "observations/#{night.slug}/", type: "article", title: night.title, description: night.summary, hero: cover(night), hero_alt: cover_alt(night), date: night.date, card: card}

    pictures =
      Enum.map_join(night.objects, "\n", fn o ->
        [w, h] = o["thumb"] || [o["width"], o["height"]]

        """
        <li>
          <a href="#{o["slug"]}.html">
            <span class="frame"><img src="images/#{o["slug"]}-thumb.jpg" width="#{w}" height="#{h}" alt="" loading="lazy" /></span>
            <strong>#{esc(o["title"])}</strong>
            <span class="detail">#{esc(o["subtitle"])}</span>
          </a>
        </li>
        """
      end)

    layout(night.title, share_tags(share, site), """
    <template id="ogplus">#{card}</template>
    <p class="back"><a href="../">‹ Observations</a></p>
    <header>
      <h1>#{esc(night.title)}</h1>
      <p class="lede">#{esc(night.summary)}</p>
    </header>
    <ul class="sky">#{pictures}</ul>
    <article class="night-notes">
      #{night.html}
    </article>
    #{spec_list(night.rows)}
    #{rights(night.date.year)}
    """, "wide", "../../", "obs")
  end

  defp object_page(night, o, site) do
    slug = o["slug"]
    i = Enum.find_index(night.objects, &(&1["slug"] == slug))
    before = if i > 0, do: Enum.at(night.objects, i - 1)
    next = Enum.at(night.objects, i + 1)
    card = object_card(night, o)

    share = %{
      path: "observations/#{night.slug}/#{slug}.html",
      type: "article",
      title: o["title"],
      description: o["what"],
      hero: "observations/#{night.slug}/images/#{web_size(night, slug)}",
      hero_alt: o["title"],
      date: night.date,
      card: card
    }

    # a picture with names on it is read, not glanced at: it may run taller than the screen, and a phone pans across it
    pan = if o["height"] > o["width"] * 0.9, do: "pan tall", else: "pan"
    hint = ~s(<p class="pan-hint">Swipe sideways to see the rest. Tap the picture for full size.</p>)
    frames = if o["frames"], do: plate(night, slug <> "-frames", "#{o["title"]}, with the frames that were joined outlined", o, pan) <> hint, else: ""

    layout(o["title"], share_tags(share, site), """
    <template id="ogplus">#{card}</template>
    <p class="back"><a href="./">‹ #{esc(night.title)}</a></p>
    #{plate(night, slug, o["title"], o)}
    <header>
      <h1>#{esc(o["title"])}</h1>
      <p class="sub">#{esc(o["subtitle"])}</p>
      <p class="what">#{esc(o["what"])}</p>
    </header>
    <section>
      <h2>What you are looking at</h2>
      #{plate(night, slug <> "-labels", "#{o["title"]}, with its parts named, a scale bar and north marked", o, pan)}
      #{hint}
      #{spec_list(o["facts"], "facts")}
    </section>
    <section>
      <h2>For photographers</h2>
      <p class="lede">#{esc(o["how"])}.</p>
      #{frames}
      #{spec_list(o["specs"])}
    </section>
    <p class="credit">#{esc(night.credit)}<br />#{esc(night.made_with)}</p>
    <nav class="prevnext">
      #{object_link(before, "earlier", "Previous")}
      #{object_link(next, "later", "Next")}
    </nav>
    #{rights(night.date.year)}
    """, "wide", "../../", "obs")
  end

  # A picture at the width of the page, the full-size file behind it. A phone
  # gets the 1600-wide copy when the picture is larger than that.
  defp plate(night, stem, alt, o, class \\ "") do
    {src, srcset} =
      if File.exists?(Path.join([night.dir, "images", stem <> "-1600.jpg"])) do
        {"images/#{stem}-1600.jpg", ~s| srcset="images/#{stem}-1600.jpg 1600w, images/#{stem}.jpg #{o["width"]}w" sizes="(min-width: 80rem) 78rem, 100vw"|}
      else
        {"images/#{stem}.jpg", ""}
      end

    # a phone pans a labelled picture at 46rem; one narrower than that pans at its own width, never above its pixels
    own = if o["width"] < 736, do: ~s( style="width:#{o["width"]}px"), else: ""

    ~s(<figure class="plate #{class}"><a href="images/#{stem}.jpg"><img src="#{src}"#{srcset} width="#{o["width"]}" height="#{o["height"]}"#{own} alt="#{esc(alt)}" /></a></figure>)
  end

  defp web_size(night, slug) do
    if File.exists?(Path.join([night.dir, "images", slug <> "-1600.jpg"])), do: slug <> "-1600.jpg", else: slug <> ".jpg"
  end

  defp cover(%{objects: [o | _]} = night), do: "observations/#{night.slug}/images/#{web_size(night, o["slug"])}"
  defp cover(_), do: nil
  defp cover_alt(%{objects: [o | _]}), do: o["title"]
  defp cover_alt(_), do: ""

  # A label over its value, one pair per cell.
  defp spec_list(rows, class \\ "spec")
  defp spec_list([], _), do: ""

  defp spec_list(rows, class) do
    cells =
      Enum.map_join(rows, "\n", fn row ->
        {k, v} = if is_list(row), do: List.to_tuple(row), else: row
        "<div><dt>#{esc(k)}</dt><dd>#{esc(v)}</dd></div>"
      end)

    ~s(<dl class="#{class}">\n#{cells}\n</dl>)
  end

  defp object_link(nil, _, _), do: ~s(<span></span>)

  defp object_link(o, class, label) do
    """
    <a href="#{o["slug"]}.html" class="#{class}">
      <span class="dir">#{label}</span>
      <strong>#{esc(o["title"])}</strong>
    </a>
    """
  end

  defp count([_]), do: "one picture"
  defp count(list), do: "#{length(list)} pictures"

  # -- share cards -------------------------------------------------------------------------
  # OpenGraph+ swaps a page's body for its <template id="ogplus"> and
  # photographs that, so a gallery page's link preview is its picture edge to
  # edge with its name and headline facts, not a screenshot of the page. The
  # page's stylesheet does not apply inside a template: every style is inline,
  # and sizes are in vw and vh so the card holds at any size it is rendered.
  @card_font "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'Segoe UI', Roboto, 'Noto Sans', Arial, sans-serif"
  @card_mark "Brad Gessler · Observatory"

  @doc false
  def object_card(night, o) do
    src = "images/#{o["card"] || web_size(night, o["slug"])}"
    # the headline facts are the short ones; a long one belongs on the page
    facts = o["facts"] |> Enum.filter(fn [_, v] -> String.length(v) <= 36 end) |> Enum.take(3)

    body =
      cond do
        # a picture narrower than the card (a small nebula at the sensor's own scale) is shown whole at no more than its
        # own pixels, never stretched to fill the card
        is_nil(o["card"]) and o["width"] < 1200 ->
          native(card_words(o, facts, "column", "1.6vw"), src, o["width"], o["height"])

        # a tall or square picture stands whole on the right, the words beside it
        o["height"] > o["width"] * 0.9 ->
          beside(card_words(o, facts, "column", "1.6vw"), src)

        true ->
          # the words go where the picture is quiet: its foot, or its head when the foot is the busy part
          {edge, fade, mark_edge} = if o["card_text"] == "top", do: {"top:3.4vw", "to bottom", "bottom:3vw"}, else: {"bottom:3.4vw", "to top", "top:3vw"}

          """
          <img src="#{src}" alt="" style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;" />
          <div style="position:absolute;top:0;left:0;width:100%;height:100%;background:linear-gradient(#{fade},rgba(0,0,0,.9) 0%,rgba(0,0,0,.6) 30%,rgba(0,0,0,0) 62%);"></div>
          <div style="position:absolute;left:4vw;right:4vw;#{edge};">#{card_words(o, facts, "row", "3.6vw")}</div>
          <div style="position:absolute;right:4vw;#{mark_edge};font-size:1.5vw;color:#e2e2de;text-shadow:0 0 .8vw #000,0 0 .3vw #000;">#{@card_mark}</div>
          """
      end

    card(body)
  end

  defp card_words(o, facts, direction, gap) do
    cells =
      Enum.map_join(facts, "\n", fn [k, v] ->
        ~s(<div><div style="font-size:1.45vw;color:#b8b8b4;">#{esc(k)}</div><div style="font-size:2.3vw;font-weight:600;line-height:1.25;">#{esc(v)}</div></div>)
      end)

    """
    <div style="font-size:5.4vw;font-weight:700;line-height:1.05;letter-spacing:-.01em;">#{esc(o["title"])}</div>
    <div style="font-size:2.2vw;color:#cfcfcb;margin-top:.7vw;">#{esc(o["subtitle"])}</div>
    <div style="display:flex;flex-direction:#{direction};gap:#{gap};margin-top:2.4vw;">#{cells}</div>
    """
  end

  # Words on the left, a picture at the card's full height on the right: whole
  # when it is tall, its middle when it is wide (never more than half the card).
  defp beside(words, src) do
    """
    <div style="display:flex;width:100%;height:100%;">
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:flex-end;padding:4vw;box-sizing:border-box;">
        <div style="margin-bottom:auto;font-size:1.5vw;color:#b8b8b4;">#{@card_mark}</div>
        #{words}
      </div>
      <img src="#{src}" alt="" style="height:100%;width:auto;max-width:52%;object-fit:cover;display:block;" />
    </div>
    """
  end

  # Words on the left, a picture smaller than the card on the right, whole and
  # at no more than its own pixels (width and height are its own; the max-
  # sizes only ever shrink it), centred on the card's black.
  defp native(words, src, w, h) do
    """
    <div style="display:flex;width:100%;height:100%;">
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:flex-end;padding:4vw;box-sizing:border-box;">
        <div style="margin-bottom:auto;font-size:1.5vw;color:#b8b8b4;">#{@card_mark}</div>
        #{words}
      </div>
      <div style="width:56%;flex:none;display:flex;align-items:center;justify-content:center;">
        <img src="#{src}" alt="" width="#{w}" height="#{h}" style="display:block;width:auto;height:auto;max-width:100%;max-height:100%;" />
      </div>
    </div>
    """
  end

  # A post: its date and title beside its hero picture. The heroes are mostly
  # screenshots of a phone, small and tall, so the picture is shown whole and
  # never stretched across the card. A long title is set smaller.
  @doc false
  def post_card(post) do
    size = if String.length(post.title) <= 32, do: "5vw", else: "3.7vw"

    words = """
    <div style="font-size:1.6vw;color:#b8b8b4;">#{pretty(post.date)}</div>
    <div style="font-size:#{size};font-weight:700;line-height:1.1;letter-spacing:-.01em;margin-top:1vw;">#{esc(post.title)}</div>
    """

    case post.hero do
      nil ->
        card("""
        <div style="display:flex;flex-direction:column;justify-content:flex-end;width:100%;height:100%;padding:5vw;box-sizing:border-box;">
          <div style="margin-bottom:auto;font-size:1.5vw;color:#b8b8b4;">#{@card_mark}</div>
          #{words}
          <div style="font-size:1.9vw;color:#cfcfcb;line-height:1.4;margin-top:1.6vw;">#{esc(post.summary)}</div>
        </div>
        """)

      src ->
        card(beside(words, src))
    end
  end

  # A night, or all of them: the words on the left, six of its pictures on the right.
  @doc false
  def collage_card(title, text, night, prefix) do
    pictures =
      night.objects
      |> Enum.take(6)
      |> Enum.map_join("\n", fn o ->
        ~s(<div style="min-width:0;min-height:0;overflow:hidden;"><img src="#{prefix}images/#{o["slug"]}-thumb.jpg" alt="" style="width:100%;height:100%;object-fit:cover;display:block;" /></div>)
      end)

    card("""
    <div style="display:flex;width:100%;height:100%;">
      <div style="width:41%;display:flex;flex-direction:column;justify-content:flex-end;padding:4vw;box-sizing:border-box;">
        <div style="margin-bottom:auto;font-size:1.5vw;color:#b8b8b4;">#{@card_mark}</div>
        <div style="font-size:4.6vw;font-weight:700;line-height:1.05;letter-spacing:-.01em;">#{esc(title)}</div>
        <div style="font-size:1.85vw;color:#cfcfcb;margin-top:1.5vw;line-height:1.4;">#{esc(text)}</div>
      </div>
      <div style="flex:1;min-width:0;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(2,1fr);gap:.3vw;">#{pictures}</div>
    </div>
    """)
  end

  # The card takes its size from the viewport, not from its parent: OpenGraph+
  # puts a template's content in a body of no set height, where height:100%
  # is nothing (a card of absolutely placed parts came out blank, 4 Oct 2026).
  defp card(body) do
    ~s(<div style="position:relative;width:100vw;height:100vh;overflow:hidden;background:#000;color:#fff;font-family:#{@card_font};">\n#{body}</div>)
  end

  defp etag(html), do: :crypto.hash(:sha256, html) |> Base.encode16(case: :lower) |> binary_part(0, 12)

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
      # a page with its own card is drawn for 1200; one without is photographed
      # as it stands, at about the article column's width
      {"property", "og:plus:viewport:width", site.ogplus && if(page[:card], do: "1200", else: "800")},
      {"property", "og:plus:style", site.ogplus && page[:card] && "margin:0;padding:0;background:#000"},
      # looked at again every hour, drawn again only when the card has changed.
      # An hour and no longer: a render taken in the minutes after a publish
      # can be of the old page (GitHub Pages caches a page 10 minutes per
      # edge), and it should not stand for a day.
      {"property", "og:plus:cache:max_age", site.ogplus && page[:card] && "3600"},
      {"property", "og:plus:cache:etag", site.ogplus && page[:card] && etag(page[:card])}
    ]
    |> Enum.reject(fn {_, _, content} -> content in [nil, ""] end)
    |> Enum.map_join("\n", fn {attr, key, content} ->
      ~s(<meta #{attr}="#{key}" content="#{esc(content)}" />)
    end)
  end

  # `root` is the way back to the site's root from this page ("" at the top,
  # "../../" two folders down); `body` is a class for the whole page.
  defp layout(title, head, inner, class \\ "", root \\ "", body \\ "") do
    """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>#{esc(title)} · #{@site_name}</title>
    #{head}
    <link rel="stylesheet" href="#{root}style.css" />
    </head>
    <body#{if body != "", do: ~s( class="#{body}")}>
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
    a:focus-visible { outline:2px solid var(--accent); outline-offset:4px; border-radius:4px; }
    /* Observations: pictures of the sky sit on true black, whatever the theme */
    body.obs { color-scheme:dark; --bg:#000; --panel:#101013; --line:#2a2a30; --text:#ecece8; --dim:#a6a6a2; --accent:#8ab4ff; }
    body.obs main.wide { max-width:80rem; }
    body.obs header { max-width:46rem; }
    body.obs h1 { font-size:2.75rem; line-height:1.08; letter-spacing:-.01em; }
    body.obs header .lede { font-size:1.15rem; }
    a.night { display:block; background:#000; border:1px solid var(--line); border-radius:16px; overflow:hidden; text-decoration:none; color:inherit; margin-top:2.5rem; }
    a.night .strip { display:grid; grid-template-columns:repeat(4,1fr); background:#000; }
    a.night .strip img { width:100%; aspect-ratio:1; object-fit:cover; display:block; }
    a.night h2 { font-size:1.2rem; margin:0 0 .15rem; color:var(--accent); }
    a.night p { color:var(--dim); margin:.5rem 0 0; font-size:.95rem; }
    a.night .card-body { background:var(--panel); }
    ul.nights { list-style:none; padding:0; margin:0; }
    ul.sky { list-style:none; padding:0; margin:3rem 0 4rem; display:grid; gap:3rem 2rem; grid-template-columns:repeat(auto-fill,minmax(19rem,1fr)); }
    /* the first picture leads: twice the size, where there is room for three across */
    @media (min-width:64rem) { ul.sky { grid-template-columns:repeat(3,1fr); } ul.sky li:first-child { grid-column:span 2; grid-row:span 2; } }
    ul.sky a { display:block; color:inherit; text-decoration:none; }
    ul.sky .frame { display:block; aspect-ratio:3/2; }
    /* every picture whole, and a small one at its own size: scale-down shrinks to fit but never enlarges */
    ul.sky img { width:100%; height:100%; object-fit:scale-down; display:block; transition:filter .12s ease; }
    ul.sky a:hover img { filter:brightness(1.15); }
    ul.sky strong { display:block; margin-top:.9rem; font-weight:600; }
    ul.sky .detail { color:var(--dim); font-size:.9rem; }
    .night-notes { max-width:46rem; }
    figure.plate { margin:1.5rem 0 2rem; text-align:center; }
    figure.plate a { display:inline-block; max-width:100%; }
    figure.plate img { display:block; max-width:100%; max-height:92vh; width:auto; height:auto; margin:0 auto; }
    figure.plate.pan img { max-height:none; }
    figure.plate.pan.tall img { max-width:min(100%,46rem); }
    .pan-hint { display:none; color:var(--dim); font-size:.85rem; margin:-1.25rem 0 0; }
    .obs .sub { color:var(--dim); margin:0; }
    .obs .what { font-size:1.3rem; line-height:1.5; }
    .obs section { margin-top:4rem; }
    .obs section > h2 { font-size:1.6rem; margin:0 0 .25rem; }
    .obs section > .lede { margin:0; max-width:46rem; }
    dl.spec, dl.facts { display:grid; gap:1.5rem 2rem; margin:2rem 0 0; }
    dl.facts { grid-template-columns:repeat(auto-fit,minmax(14rem,1fr)); }
    dl.spec { grid-template-columns:repeat(auto-fit,minmax(18rem,1fr)); }
    dl.spec div, dl.facts div { border-top:1px solid var(--line); padding-top:.7rem; }
    dl.spec dt, dl.facts dt { color:var(--dim); font-size:.85rem; }
    dl.spec dd, dl.facts dd { margin:.2rem 0 0; }
    dl.facts dd { font-size:1.35rem; line-height:1.35; font-weight:600; }
    dl.spec dd { font-size:.95rem; line-height:1.5; }
    .credit { color:var(--dim); font-size:.85rem; margin-top:4rem; }
    .rights { color:var(--dim); font-size:.85rem; margin-top:3rem; }
    /* a phone: the pictures run edge to edge, the words keep their margin */
    @media (max-width:40rem) {
      body.obs h1 { font-size:2.1rem; }
      body.obs main { padding-top:1.5rem; }
      figure.plate { margin-left:-1.25rem; margin-right:-1.25rem; }
      figure.plate.pan { overflow-x:auto; }
      figure.plate.pan a { display:block; width:max-content; max-width:none; }
      figure.plate.pan img, figure.plate.pan.tall img { width:46rem; max-width:none; }
      .pan-hint { display:block; }
      ul.sky { gap:2.5rem; margin-top:2rem; }
      ul.sky .frame { margin:0 -1.25rem; aspect-ratio:auto; }
      ul.sky img { height:auto; max-height:80vh; }
      .obs .what { font-size:1.15rem; }
      dl.facts { grid-template-columns:1fr 1fr; gap:1.25rem 1rem; }
      dl.facts dd { font-size:1.15rem; }
    }
    /* OpenGraph+ sets data-ogplus while it photographs a page for its share card */
    html[data-ogplus] .back { display:none; }
    """
  end
end
