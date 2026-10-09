defmodule Mix.Tasks.Site.BuildTest do
  # the task reads posts/ from the working directory, and File.cd!/2 moves the
  # whole VM's, so these run on their own
  use ExUnit.Case, async: false

  import ExUnit.CaptureIO

  @moduletag :tmp_dir
  @site "https://bradgessler.github.io/observatory-blog"

  setup %{tmp_dir: dir} do
    File.mkdir_p!(Path.join(dir, "posts/images"))
    File.write!(Path.join(dir, "posts/images/first.png"), "")

    File.write!(Path.join(dir, "posts/2026-09-19-first-light.md"), """
    ---
    title: "First light"
    date: 2026-09-19
    summary: A "quick look" at Venus & the mount
    hero: "images/first.png"
    hero_alt: "Venus in the eyepiece"
    ---

    The scope moved.
    """)

    :ok
  end

  defp build(dir, args) do
    File.cd!(dir, fn -> capture_io(fn -> Mix.Tasks.Site.Build.run(args) end) end)

    {File.read!(Path.join(dir, "_site/index.html")),
     File.read!(Path.join(dir, "_site/2026-09-19-first-light.html"))}
  end

  test "a published image carries no EXIF, GPS or text; the picture is untouched" do
    jfif = <<0xFF, 0xE0, 16::16, "JFIF", 0, 1, 1, 0, 0, 1, 0, 1, 0, 0>>
    exif = "Exif" <> <<0, 0>> <> "GPSLatitude 12.3456"
    app1 = <<0xFF, 0xE1, byte_size(exif) + 2::16>> <> exif
    scan = <<0xFF, 0xDA, 0, 8, 1, 2, 3, 4, 5, 6, 0xAB, 0xCD, 0xFF, 0xD9>>
    jpeg = <<0xFF, 0xD8>> <> jfif <> app1 <> scan

    out = Mix.Tasks.Site.Build.strip_jpeg(jpeg)
    refute out =~ "GPSLatitude"
    assert out == <<0xFF, 0xD8>> <> jfif <> scan

    sig = <<137, 80, 78, 71, 13, 10, 26, 10>>
    chunk = fn type, data -> <<byte_size(data)::32, type::binary, data::binary, 0::32>> end
    png = sig <> chunk.("IHDR", "hdr") <> chunk.("tEXt", "Location\0somewhere") <> chunk.("IDAT", "pix") <> chunk.("IEND", "")
    stripped = Mix.Tasks.Site.Build.strip_png(png)
    refute stripped =~ "somewhere"
    assert stripped == sig <> chunk.("IHDR", "hdr") <> chunk.("IDAT", "pix") <> chunk.("IEND", "")
  end

  test "a post that names the town or gives coordinates to a decimal is refused", %{tmp_dir: dir} do
    old = Application.get_env(:controller, :site)
    Application.put_env(:controller, :site, %{name: "Testville", lat: 12.3456, lon: -65.4321})

    try do
      File.write!(Path.join(dir, "posts/2026-09-20-oops.md"), "---\ntitle: \"Oops\"\ndate: 2026-09-20\n---\n\nOut in testville tonight.\n")
      assert_raise Mix.Error, ~r/Bay Area/, fn -> build(dir, ["--ogplus", ""]) end

      File.write!(Path.join(dir, "posts/2026-09-20-oops.md"), "---\ntitle: \"Oops\"\ndate: 2026-09-20\n---\n\nAt 12.35 N tonight.\n")
      assert_raise Mix.Error, fn -> build(dir, ["--ogplus", ""]) end

      File.write!(Path.join(dir, "posts/2026-09-20-oops.md"), "---\ntitle: \"Fine\"\ndate: 2026-09-20\n---\n\nSomewhere in the Bay Area tonight.\n")
      assert {_, _} = build(dir, ["--ogplus", ""])
    after
      if old, do: Application.put_env(:controller, :site, old), else: Application.delete_env(:controller, :site)
    end
  end

  test "with OpenGraph+, og:image is its render of the page's own path", %{tmp_dir: dir} do
    {index, post} = build(dir, ["--ogplus", "https://test.ogplus.net/"])

    assert post =~
             ~s(<meta property="og:image" content="https://test.ogplus.net/observatory-blog/2026-09-19-first-light.html" />)

    assert post =~ ~s(<meta property="og:url" content="#{@site}/2026-09-19-first-light.html" />)
    assert post =~ ~s(<meta property="og:type" content="article" />)
    assert post =~ ~s(<meta property="og:title" content="First light" />)

    assert post =~
             ~s(<meta property="og:description" content="A &quot;quick look&quot; at Venus &amp; the mount" />)

    assert post =~ ~s(<meta property="article:published_time" content="2026-09-19" />)
    assert post =~ ~s(<meta name="twitter:card" content="summary_large_image" />)
    # the render is of the post's own card: its date and title beside its hero picture
    assert post =~ ~s(<meta property="og:plus:viewport:width" content="1200" />)
    [_, card] = Regex.run(~r{<template id="ogplus">(.*?)</template>}s, post)
    assert card =~ "First light"
    assert card =~ "19 September 2026"
    assert card =~ ~s(<img src="images/first.png")
    refute card =~ "class="
    refute post =~ "og:image:alt"

    assert index =~
             ~s(<meta property="og:image" content="https://test.ogplus.net/observatory-blog/" />)

    assert index =~ ~s(<meta property="og:url" content="#{@site}/" />)
    assert index =~ ~s(<meta property="og:type" content="website" />)
  end

  test "without OpenGraph+, a page shares with its hero picture", %{tmp_dir: dir} do
    {index, post} = build(dir, ["--ogplus", ""])

    assert post =~ ~s(<meta property="og:image" content="#{@site}/images/first.png" />)
    assert post =~ ~s(<meta property="og:image:alt" content="Venus in the eyepiece" />)
    assert post =~ ~s(<meta name="twitter:card" content="summary_large_image" />)
    refute post =~ "ogplus.net"
    refute post =~ "og:plus:"

    assert index =~ ~s(<meta property="og:image" content="#{@site}/images/first.png" />)
  end

  describe "observations" do
    setup %{tmp_dir: dir} do
      night = Path.join(dir, "observations/2026-10-03")
      File.mkdir_p!(Path.join(night, "images"))

      File.write!(Path.join(night, "session.md"), """
      ---
      title: "Night of 3 October 2026"
      date: 2026-10-03
      summary: "Two pictures from one night."
      Location: San Francisco Bay Area
      Camera: Sony a6000, stock: APS-C
      ---

      Thin cloud all night.
      """)

      object = fn slug, title, w, h, more ->
        Map.merge(
          %{
            slug: slug,
            title: title,
            subtitle: "Messier 42",
            what: "A cloud of gas & dust.",
            facts: [["Distance", "1,344 light-years"], ["For scale", "Neptune's whole orbit would cover a fifth of one pixel"]],
            how: "13 minutes of light",
            specs: [["Exposures", "39 x 20 s at ISO 3200"]],
            width: w,
            height: h,
            thumb: [900, 598],
            frames: false
          },
          more
        )
      end

      File.write!(
        Path.join(night, "objects.json"),
        Jason.encode!(%{
          credit: "Brad Gessler · San Francisco Bay Area",
          made_with: "Nothing generated.",
          objects: [object.("orion-nebula", "The Orion Nebula", 3002, 1995, %{frames: true}), object.("moon", "The Moon", 3036, 5434, %{card_text: "top"})]
        })
      )

      exif = "Exif" <> <<0, 0>> <> "GPSLatitude 12.3456"
      jpeg = <<0xFF, 0xD8, 0xFF, 0xE1, byte_size(exif) + 2::16>> <> exif <> <<0xFF, 0xDA, 0, 2, 0xFF, 0xD9>>
      for f <- ~w(orion-nebula.jpg orion-nebula-1600.jpg orion-nebula-thumb.jpg orion-nebula-labels.jpg orion-nebula-frames.jpg moon.jpg moon-thumb.jpg moon-labels.jpg), do: File.write!(Path.join([night, "images", f]), jpeg)

      {:ok, night: night}
    end

    defp page(dir, path), do: File.read!(Path.join([dir, "_site/observations", path]))

    test "a night is a grid of its pictures, each opening its own page; the home page leads there", %{tmp_dir: dir} do
      {index, _post} = build(dir, ["--ogplus", ""])
      assert index =~ ~s(<a class="night" href="observations/">)
      assert index =~ "Latest: Night of 3 October 2026, 2 pictures."

      assert page(dir, "index.html") =~ ~s(<a class="night" href="2026-10-03/">)

      night = page(dir, "2026-10-03/index.html")
      assert night =~ ~s(<body class="obs">)
      assert night =~ ~s(<link rel="stylesheet" href="../../style.css" />)
      assert night =~ ~s(<a href="orion-nebula.html">)
      assert night =~ ~s(<img src="images/moon-thumb.jpg" width="900" height="598" alt="" loading="lazy" />)
      assert night =~ "Thin cloud all night."
      # the night's facts keep the order and the labels the file gives them, and a value may hold a colon
      assert night =~ ~r{<dt>Location</dt><dd>San Francisco Bay Area</dd></div>\s*<div><dt>Camera</dt><dd>Sony a6000, stock: APS-C</dd>}
      refute night =~ "<dt>title</dt>"
    end

    test "a picture's page: the plain picture, then the labelled one with its facts, then the part for photographers", %{tmp_dir: dir} do
      build(dir, ["--ogplus", ""])
      html = page(dir, "2026-10-03/orion-nebula.html")

      [plain, labels, frames] = for stem <- ~w(orion-nebula orion-nebula-labels orion-nebula-frames), do: elem(:binary.match(html, ~s(<a href="images/#{stem}.jpg">)), 0)
      assert plain < labels and labels < frames
      {facts, _} = :binary.match(html, ~s(<dl class="facts">))
      {specs, _} = :binary.match(html, ~s(<dl class="spec">))
      assert labels < facts and facts < frames and frames < specs

      # a phone gets the 1600-wide copy; the full size is one tap away
      assert html =~ ~s(srcset="images/orion-nebula-1600.jpg 1600w, images/orion-nebula.jpg 3002w")
      assert html =~ "A cloud of gas &amp; dust."
      assert html =~ "<dt>Exposures</dt><dd>39 x 20 s at ISO 3200</dd>"
      assert html =~ ~s(<a href="moon.html" class="later">)

      # a single field has no frames picture, and a picture with no 1600 copy is served as it is
      moon = page(dir, "2026-10-03/moon.html")
      refute moon =~ "moon-frames.jpg"
      assert moon =~ ~s(<img src="images/moon.jpg" width="3036" height="5434")
      assert moon =~ ~s(<figure class="plate pan tall">)
    end

    test "a picture's page shares as its own card, drawn by OpenGraph+ from a template", %{tmp_dir: dir} do
      build(dir, ["--ogplus", "https://test.ogplus.net"])
      html = page(dir, "2026-10-03/orion-nebula.html")

      assert html =~ ~s(<meta property="og:image" content="https://test.ogplus.net/observatory-blog/observations/2026-10-03/orion-nebula.html" />)
      assert html =~ ~s(<meta property="og:plus:viewport:width" content="1200" />)
      assert html =~ ~r|<meta property="og:plus:cache:etag" content="[0-9a-f]{12}" />|

      [_, card] = Regex.run(~r{<template id="ogplus">(.*?)</template>}s, html)
      assert card =~ ~s(<img src="images/orion-nebula-1600.jpg")
      assert card =~ "The Orion Nebula"
      assert card =~ "1,344 light-years"
      # only the short facts make the card
      refute card =~ "Neptune"
      # nothing in a template can lean on the page's stylesheet
      refute card =~ "class="

      assert page(dir, "2026-10-03/index.html") =~ ~s(<template id="ogplus">)
      # the home page's card is the site's name beside the newest night's pictures
      [_, home] = Regex.run(~r{<template id="ogplus">(.*?)</template>}s, File.read!(Path.join(dir, "_site/index.html")))
      assert home =~ ~s(<img src="observations/2026-10-03/images/orion-nebula-thumb.jpg")
    end

    test "a picture smaller than the page is never drawn above its own pixels: not on a phone, not in the grid, not on its card", %{tmp_dir: dir, night: night} do
      json = night |> Path.join("objects.json") |> File.read!() |> Jason.decode!()
      small = %{"slug" => "m76", "title" => "The Little Dumbbell Nebula", "subtitle" => "Messier 76", "what" => "A dying star.", "facts" => [["Distance", "2,500 light-years"]],
                "how" => "5.5 minutes", "specs" => [], "width" => 640, "height" => 480, "thumb" => [640, 480], "frames" => false}
      File.write!(Path.join(night, "objects.json"), Jason.encode!(%{json | "objects" => json["objects"] ++ [small]}))
      for f <- ~w(m76.jpg m76-thumb.jpg m76-labels.jpg), do: File.write!(Path.join([night, "images", f]), "")

      build(dir, ["--ogplus", "https://test.ogplus.net"])
      html = page(dir, "2026-10-03/m76.html")
      # a phone pans the labelled picture at its own width, not at 46rem
      assert html =~ ~s(<img src="images/m76-labels.jpg" width="640" height="480" style="width:640px")
      refute page(dir, "2026-10-03/orion-nebula.html") =~ ~s(style="width:)

      # its card shows it whole at its own size beside the words, not stretched across the card
      [_, card] = Regex.run(~r{<template id="ogplus">(.*?)</template>}s, html)
      assert card =~ ~s(<img src="images/m76.jpg" alt="" width="640" height="480" style="display:block;width:auto;height:auto;max-width:100%;max-height:100%;")
      assert card =~ "The Little Dumbbell Nebula"
      refute card =~ "object-fit:cover"
      refute card =~ "class="

      # the night's grid shrinks a picture to fit its tile but never enlarges one
      assert File.read!(Path.join(dir, "_site/style.css")) =~ "ul.sky img { width:100%; height:100%; object-fit:scale-down;"
    end

    test "without OpenGraph+, a picture's page shares with the picture itself", %{tmp_dir: dir} do
      build(dir, ["--ogplus", ""])
      html = page(dir, "2026-10-03/orion-nebula.html")
      assert html =~ ~s(<meta property="og:image" content="#{@site}/observations/2026-10-03/images/orion-nebula-1600.jpg" />)
      refute html =~ "og:plus:"
    end

    test "a night's pictures are published without their metadata", %{tmp_dir: dir} do
      build(dir, ["--ogplus", ""])
      refute File.read!(Path.join(dir, "_site/observations/2026-10-03/images/orion-nebula.jpg")) =~ "GPSLatitude"
    end

    test "a night that names the town, in its notes or its pictures' words, is refused", %{tmp_dir: dir, night: night} do
      old = Application.get_env(:controller, :site)
      Application.put_env(:controller, :site, %{name: "Testville", lat: 12.3456, lon: -65.4321})

      try do
        assert {_, _} = build(dir, ["--ogplus", ""])

        json = File.read!(Path.join(night, "objects.json"))
        File.write!(Path.join(night, "objects.json"), String.replace(json, "A cloud of gas", "Seen from Testville: a cloud of gas"))
        assert_raise Mix.Error, ~r{observations/2026-10-03/objects.json}, fn -> build(dir, ["--ogplus", ""]) end

        File.write!(Path.join(night, "objects.json"), json)
        File.write!(Path.join(night, "session.md"), "---\ntitle: \"Oops\"\nLocation: Testville\n---\n")
        assert_raise Mix.Error, ~r{observations/2026-10-03/session.md}, fn -> build(dir, ["--ogplus", ""]) end
      after
        if old, do: Application.put_env(:controller, :site, old), else: Application.delete_env(:controller, :site)
      end
    end
  end

  test "a post's link to a night, written from posts/ as the repository lays it out, works from the site's root", %{tmp_dir: dir} do
    File.write!(Path.join(dir, "posts/2026-10-08-night.md"), "---\ntitle: \"A night\"\ndate: 2026-10-08\n---\n\nThe pictures have [their own page](../observations/2026-10-03/).\n")
    build(dir, ["--ogplus", ""])
    html = File.read!(Path.join(dir, "_site/2026-10-08-night.html"))
    assert html =~ ~s(<a href="observations/2026-10-03/">their own page</a>)
    refute html =~ "../observations"
  end

  test "every image is a figure with its caption, and tables scroll on a phone" do
    html =
      Mix.Tasks.Site.Build.render("""
      ![The alt](images/a.jpg "The caption.")

      ![Only alt](images/b.png)

      | a | b |
      |---|---|
      | 1 | 2 |
      """)
    assert html =~ ~s(<figure><img src="images/a.jpg" alt="The alt" loading="lazy" /><figcaption>The caption.</figcaption></figure>)
    assert html =~ ~s(<figcaption>Only alt</figcaption>)
    assert html =~ ~s(<div class="table-wrap"><table>)
    refute html =~ "<p><img"
  end
end
