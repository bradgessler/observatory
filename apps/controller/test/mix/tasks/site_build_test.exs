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
    assert post =~ ~s(<meta property="og:plus:viewport:width" content="800" />)
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
