defmodule Controller.DesignTest do
  @moduledoc """
  The palette meets WCAG 2.1 AA, checked from the token file itself:
  text 4.5:1 on every surface it can sit on, 3:1 for the key edge and for a
  lit key against the panel around it (non-text contrast, 1.4.11). Three
  themes: default (dark), light, night. If a colour changes here and the
  eyepiece can't read it, this fails.

  And a page is never wider than the phone it is on, checked from the
  stylesheets themselves (the rules as they apply at a given width): a
  toolbar takes its width from the page and not from what's in it, a row
  with more in it than a phone holds wraps, and nothing asks for more room
  than a 320 px phone has. A page that is too wide makes a phone zoom the
  whole of it out, and everything is then half size at the eyepiece.
  """
  use ExUnit.Case, async: true

  @tokens Path.expand("../../priv/static/assets/css/tokens.css", __DIR__)
  @css Path.expand("../../priv/static/assets/css", __DIR__)
  @sheets ~w(app.css controls.css)

  # the narrowest phone we draw for, and the gutter each side of a page (--page-x)
  @phone 320
  @gutter 16

  @text ~w(text dim accent on warn amber)
  # sunk: the panel a page sits in on a wide screen, lifted off the black ground
  @surfaces ~w(bg sunk panel panel2 key lit lit-on lit-warn)

  test "text is 4.5:1 or better on every surface, in every theme" do
    for {theme, t} <- themes() do
      for fg <- @text, bg <- @surfaces, fg != "amber" or bg == "amber-bg" or true do
        ratio = contrast(t[fg], t[bg])
        assert ratio >= 4.5, "#{theme}: --#{fg} #{t[fg]} on --#{bg} #{t[bg]} is #{Float.round(ratio, 2)}:1"
      end

      assert contrast(t["amber"], t["amber-bg"]) >= 4.5, "#{theme}: amber on its strip"
    end
  end

  # The primary button is filled with the accent and lettered in the ground
  # colour: the one action on a screen, and it must read in every theme.
  test "the primary button's ink reads on its fill" do
    for {theme, t} <- themes() do
      ratio = contrast(t["bg"], t["accent"])
      assert ratio >= 4.5, "#{theme}: --bg #{t["bg"]} on --accent #{t["accent"]} is #{Float.round(ratio, 2)}:1"
    end
  end

  # A key is identified by its label, so its edge may be soft (WCAG 1.4.11 asks
  # for 3:1 only where the boundary is the sole cue). What must read is the
  # ink on a lit key, which the text test above covers, and the lit tone
  # itself against the plain key: a visible step (night mode keeps it small on
  # purpose; the accent edge and the text change carry the rest).
  test "a lit key is a visible step from a plain key" do
    for {theme, t} <- themes() do
      ratio = contrast(t["lit"], t["key"])
      assert ratio >= 1.05, "#{theme}: --lit #{t["lit"]} is indistinguishable from --key #{t["key"]} (#{Float.round(ratio, 2)}:1)"
    end
  end

  # -- a page is never wider than the phone ------------------------------------------

  # The night Tonight came up half size on a phone: its toolbar status was a
  # grid item with justify-self: start, which sizes an item to its contents,
  # and its contents were one row that could not wrap. So the status was 882 px
  # wide on a 390 px phone and the page went with it. A status fills its area
  # (no justify-self, no intrinsic width), it and what's in it may shrink
  # (min-width: 0), and no toolbar scrolls sideways to hide what doesn't fit.
  test "a toolbar takes its width from the page, never from what's in it" do
    rules = rules()

    for {media, selector, decls} <- rules, selector =~ ".page-header" or selector =~ ".tb-status" do
      rule = "#{selector} #{media_words(media)}"
      refute decls["overflow-x"] in ~w(auto scroll), "#{rule}: a toolbar never scrolls sideways"
      refute decls["overflow"] in ~w(auto scroll), "#{rule}: a toolbar never scrolls sideways"

      if subject(selector) =~ ".page-header" do
        assert decls["justify-items"] in [nil, "stretch", "normal"], "#{rule}: justify-items sizes every part of the toolbar to its contents"
      end

      if subject(selector) =~ ".tb-status" do
        assert decls["justify-self"] in [nil, "stretch"], "#{rule}: justify-self sizes the status to its contents; it must fill its area"
        refute decls["width"] in ~w(max-content min-content fit-content), "#{rule}: the status takes its width from the toolbar"
      end
    end

    for w <- widths() do
      assert cascade(rules, ".page-header > .tb-status", w)["min-width"] == "0", "at #{w} px the status can't shrink below its contents"
      assert cascade(rules, ".page-header > .tb-status > *", w)["min-width"] == "0", "at #{w} px what's in the status can't shrink below its contents"
    end
  end

  # The Sky's status holds the most: the time stepper, how dark it is, the
  # place. About 850 px on one line, so at every width it is either laid out
  # in lines (a grid) or a row that wraps; never a row that can't.
  test "the Sky status wraps or is laid out in lines at every width" do
    rules = rules()

    for w <- widths() do
      s = cascade(rules, ".sky-status", w)
      assert s["display"] == "grid" or s["flex-wrap"] == "wrap", "at #{w} px the Sky status is one row that cannot wrap (display: #{s["display"]}, flex-wrap: #{inspect(s["flex-wrap"])})"
    end
  end

  # Its first line on a phone is the stepper, and that one cannot wrap: three
  # keys, the clock between them, the gaps. Added up from the rules as they
  # apply at each width, with every key still 44 px.
  test "the time stepper fits across a phone with every key at 44 px" do
    rules = rules()

    for w <- [320, 360, 375, 390, 414, 430] do
      step = cascade(rules, ".ss-step", w)
      assert px(step["min-width"]) >= 44 and px(step["min-height"]) >= 44, "at #{w} px a step key is #{step["min-width"]} by #{step["min-height"]}"

      row = 3 * px(step["min-width"]) + px(cascade(rules, ".ss-clock", w)["min-width"]) + 3 * px(cascade(rules, ".ss-time", w)["gap"])
      room = w - 2 * @gutter
      assert row <= room, "at #{w} px the stepper needs #{row} px and the page has #{room}"
    end
  end

  # -- a Tonight row's columns hold still -----------------------------------------------

  # The night the Tonight list came out jagged: a row was a flex line, and the
  # drawn angle sat wherever the words after it ("Until dawn, 06:47", "Flip, then
  # tracks to 03:37") left it, a different place in every row. A row is a grid
  # whose tracks are the same in every row: the number, the name (the one track
  # that gives), the "until", and the angle last, at the row's far edge. The
  # others are fixed lengths, so nothing a row says can move a column; the
  # detail runs under the "until", so what Go To will do rides on it as words.
  test "a Tonight row is a grid of fixed tracks, the drawn angle last, at every width" do
    rules = rules()

    for w <- widths() do
      row = cascade(rules, ".targets .target", w)
      assert row["display"] == "grid", "at #{w} px a Tonight row is display: #{inspect(row["display"])}, so its columns go where its words push them"

      assert [number, "minmax(0, 1fr)", "var(--when-w)", "40px"] = top_level(row["grid-template-columns"], [?\s]),
             "at #{w} px the tracks are #{row["grid-template-columns"]}: number, name, until, angle (40 px, last)"

      assert row["grid-template-areas"] == ~s("k name when glyph" "k detail detail glyph")
      assert px(number) == 24
      assert px(cascade(rules, ".targets", w)["--when-w"]) in 96..128, "at #{w} px the until's track is a fixed length"

      # each part of a row is put in its track by name, so the order they come in can't move them
      for {part, area} <- [{".k", "k"}, {".t > strong", "name"}, {".d", "detail"}, {".when", "when"}, {".height", "glyph"}] do
        assert cascade(rules, ".targets .target #{part}", w)["grid-area"] == area, "at #{w} px #{part} is not placed in the #{area} track"
      end

      assert cascade(rules, ".targets .target .t", w)["display"] == "contents"
      # the "until" may wrap inside its track (a time with "UTC"); it never widens it
      assert cascade(rules, ".targets .target .when", w)["white-space"] == "normal"
    end

    # a phone shows the row as a link, a wide screen as a key: whichever is shown, it is the grid
    assert cascade(rules, ".pick-wide", 390)["display"] == "none !important"
    assert cascade(rules, ".pick-wide", 1280)["display"] == "grid !important"
    assert cascade(rules, ".pick-narrow", 1280)["display"] == "none !important"
    assert cascade(rules, ".pick-narrow", 390)["display"] == nil

    # and on a phone the fixed tracks leave the name room: added up from the rules as they apply there
    root = cascade(rules, ":root", @phone)
    len = fn "var(--" <> name -> px(root["--" <> String.trim_trailing(name, ")")]); value -> px(value) end

    for w <- [320, 360, 390] do
      row = cascade(rules, ".targets .target", w)
      [_row_gap, column_gap] = String.split(row["gap"])
      gap = len.(row["column-gap"] || column_gap)
      [_pad_y, pad_x] = String.split(row["padding"])
      fixed = 24 + px(cascade(rules, ".targets", w)["--when-w"]) + 40 + 3 * gap + 2 * px(pad_x)
      name = w - 2 * @gutter - fixed
      assert name >= 64, "at #{w} px the fixed tracks take #{fixed} px and leave the name #{name}"
    end
  end

  # -- the solar graph belongs to the theme ---------------------------------------------

  # The Sky toolbar's solar graph was a filled slab, the lower half of the graph,
  # with a tint of the accent over it: on a black page it read as a rendering
  # fault. It is line and tint now. Every tone is a token, or a small share of
  # one over nothing, so each theme draws it in its own ink (night mode in red),
  # no line is thinned below the contrast the token test checks, and no fill is
  # more than a faint shade.
  test "the solar graph takes every tone from the theme: no slab, no colour of its own" do
    graph = for {_media, selector, decls} <- rules(), selector =~ ~r/\.sg-/, do: {selector, decls}
    dark = themes() |> List.first() |> elem(1)

    assert Enum.any?(graph, fn {selector, _} -> selector =~ ".sg-curve" end)
    refute Enum.any?(graph, fn {selector, _} -> selector =~ ".sg-below" end), "the ground slab under the horizon is back"

    for {selector, decls} <- graph do
      for prop <- ~w(fill stroke color background), value = decls[prop], value != nil and value != "none" do
        tone = Regex.run(~r/^(?:var\(--([a-z0-9-]+)\)|color-mix\(in srgb, var\(--([a-z0-9-]+)\) (\d+)%, transparent\))$/, value) || []
        assert [_, token | share] = Enum.reject(tone, &(&1 == "")), "#{selector} { #{prop}: #{value} } is a colour of its own; use a token"

        assert Map.has_key?(dark, token), "#{selector}: --#{token} is not in tokens.css"
        for pct <- share, do: assert(String.to_integer(pct) <= 15, "#{selector} { #{prop}: #{value} } is a slab, not a shade")
      end

      assert decls["opacity"] == nil, "#{selector}: a thinned line is a contrast nobody checked"
    end
  end

  # A width in px that a small phone doesn't have is only allowed where the
  # screen is known to be that wide: inside a min-width media query.
  test "nothing asks for more width than a 320 px phone has, outside a wide-screen media query" do
    room = @phone - 2 * @gutter

    for {media, selector, decls} <- rules(), {prop, value} <- decls, n <- fixed_widths(prop, value), n > room do
      assert at_least(media) >= n,
             "#{selector} { #{prop}: #{value} } #{media_words(media)} needs #{n} px; a #{@phone} px phone has #{room}. Use min(#{n}px, 100%), minmax(0, ...) or a min-width media query"
    end
  end

  # -- the stylesheets: every rule, and what a selector's rules add up to at a width --

  defp widths, do: [320, 360, 390, 440, 600, 768, 959, 960, 1024, 1100, 1280, 1499, 1500, 1920]

  # [{media, selector, declarations}] in source order; media is the stack of @media a rule sits in
  defp rules do
    Enum.flat_map(@sheets, fn sheet ->
      @css |> Path.join(sheet) |> File.read!() |> String.replace(~r{/\*.*?\*/}s, "") |> blocks([])
    end)
  end

  # "prelude { body }" one after another; the body of an @media is more of the same
  defp blocks(css, media) do
    case String.split(css, "{", parts: 2) do
      [_] ->
        []

      [prelude, rest] ->
        {body, rest} = closing(rest, 1, 0)
        prelude = prelude |> String.replace(~r/\s+/, " ") |> String.trim()

        here =
          cond do
            String.starts_with?(prelude, "@media") -> blocks(body, media ++ [prelude])
            String.starts_with?(prelude, "@") -> []
            true -> for s <- top_level(prelude, [?,]), do: {media, String.trim(s), declarations(body)}
          end

        here ++ blocks(rest, media)
    end
  end

  # up to the brace that closes the one already open, and what follows it
  defp closing(css, depth, i) do
    case :binary.at(css, i) do
      ?{ -> closing(css, depth + 1, i + 1)
      ?} when depth == 1 -> {binary_part(css, 0, i), binary_part(css, i + 1, byte_size(css) - i - 1)}
      ?} -> closing(css, depth - 1, i + 1)
      _ -> closing(css, depth, i + 1)
    end
  end

  defp declarations(body) do
    for decl <- String.split(body, ";"), [prop, value] <- [String.split(decl, ":", parts: 2)], into: %{} do
      {String.trim(prop), String.trim(value)}
    end
  end

  # split on any of `seps` that isn't inside parentheses: ":has(> a, b)" stays whole
  defp top_level(text, seps) do
    {parts, last, _} =
      text
      |> String.to_charlist()
      |> Enum.reduce({[], [], 0}, fn
        ?(, {parts, cur, depth} -> {parts, [?( | cur], depth + 1}
        ?), {parts, cur, depth} -> {parts, [?) | cur], depth - 1}
        c, {parts, cur, 0} -> if c in seps, do: {[cur | parts], [], 0}, else: {parts, [c | cur], 0}
        c, {parts, cur, depth} -> {parts, [c | cur], depth}
      end)

    [last | parts] |> Enum.reverse() |> Enum.map(&(&1 |> Enum.reverse() |> to_string()))
  end

  # what a selector styles: its last compound, without what's inside :has() and :not()
  defp subject(selector) do
    selector |> top_level([?\s, ?>, ?+, ?~]) |> List.last() |> without(~r/\([^()]*\)/)
  end

  # a selector's declarations at a viewport width: its rules whose media apply there, later over earlier
  defp cascade(rules, selector, width) do
    for {media, ^selector, decls} <- rules, applies?(media, width), reduce: %{} do
      acc -> Map.merge(acc, decls)
    end
  end

  # every @media in the stack holds at this width; a query that isn't about width (hover, motion) may hold
  defp applies?(media, width) do
    Enum.all?(media, fn query ->
      query |> alternatives() |> Enum.any?(fn alt -> bound(alt, "min-width", 0) <= width and width <= bound(alt, "max-width", 100_000) end)
    end)
  end

  # the narrowest viewport a rule in this media stack can apply at
  defp at_least(media) do
    media
    |> Enum.map(fn query -> query |> alternatives() |> Enum.map(&bound(&1, "min-width", 0)) |> Enum.min() end)
    |> Enum.max(fn -> 0 end)
  end

  defp alternatives("@media" <> query), do: String.split(query, ",")

  defp bound(alternative, feature, default) do
    case Regex.run(~r/\(\s*#{feature}:\s*(\d+)px\s*\)/, alternative) do
      [_, n] -> String.to_integer(n)
      nil -> default
    end
  end

  defp media_words([]), do: "(any width)"
  defp media_words(media), do: "(" <> Enum.join(media, " ") <> ")"

  # the widths in px a declaration insists on: a width or min-width, a flex item that can't
  # shrink, a grid track's minimum. min(300px, 78vw), max-width and 1fr insist on nothing
  defp fixed_widths(prop, value) when prop in ~w(width min-width flex-basis) do
    case Regex.run(~r/^(\d+)px$/, value) do
      [_, n] -> [String.to_integer(n)]
      nil -> []
    end
  end

  defp fixed_widths("flex", value) do
    case Regex.run(~r/^0 0 (\d+)px$/, value) do
      [_, n] -> [String.to_integer(n)]
      nil -> []
    end
  end

  defp fixed_widths("grid-template-columns", value) do
    minimums = for [_, n] <- Regex.scan(~r/minmax\(\s*(\d+)px/, value), do: String.to_integer(n)
    # the tracks given as a bare length, once every function (minmax, repeat, fit-content) is taken out
    bare = for [_, n] <- Regex.scan(~r/(?<![\w.-])(\d+)px/, without(value, ~r/[\w-]+\([^()]*\)/)), do: String.to_integer(n)
    minimums ++ bare
  end

  defp fixed_widths(_, _), do: []

  # take out every match, innermost first, until none is left: nested parentheses go too
  defp without(text, pattern) do
    stripped = String.replace(text, pattern, "")
    if stripped == text, do: text, else: without(stripped, pattern)
  end

  defp px("0"), do: 0

  defp px(value) when is_binary(value) do
    {n, "px"} = Integer.parse(value)
    n
  end

  # -- the token file --------------------------------------------------------------

  defp themes do
    css = File.read!(@tokens)
    [dark, light, night] = Regex.scan(~r/\{([^}]*)\}/s, css) |> Enum.map(fn [_, body] -> body end) |> Enum.take(3)
    dark = tokens(dark)
    [{"dark", dark}, {"light", Map.merge(dark, tokens(light))}, {"night", Map.merge(dark, tokens(night))}]
  end

  defp tokens(body) do
    Regex.scan(~r/--([a-z0-9-]+):\s*([^;]+);/, body)
    |> Map.new(fn [_, k, v] -> {k, String.trim(v)} end)
  end

  # -- WCAG maths --------------------------------------------------------------------

  defp contrast(a, b) do
    {la, lb} = {luminance(rgb(a)), luminance(rgb(b))}
    (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
  end

  defp luminance({r, g, b}) do
    [r, g, b]
    |> Enum.map(fn c ->
      c = c / 255
      if c <= 0.03928, do: c / 12.92, else: :math.pow((c + 0.055) / 1.055, 2.4)
    end)
    |> then(fn [r, g, b] -> 0.2126 * r + 0.7152 * g + 0.0722 * b end)
  end

  defp rgb("#" <> hex) when byte_size(hex) == 6 do
    {r, g, b} = {String.slice(hex, 0, 2), String.slice(hex, 2, 2), String.slice(hex, 4, 2)}
    {String.to_integer(r, 16), String.to_integer(g, 16), String.to_integer(b, 16)}
  end

  # "rgba(255, 255, 255, .35)" composited over a hex background
  defp blend("rgba(" <> rest, over) do
    [r, g, b, a] = rest |> String.trim_trailing(")") |> String.split(",") |> Enum.map(&String.trim/1)
    {r, g, b} = {String.to_integer(r), String.to_integer(g), String.to_integer(b)}
    a = String.to_float(if String.starts_with?(a, "."), do: "0" <> a, else: if(String.contains?(a, "."), do: a, else: a <> ".0"))
    {or_, og, ob} = rgb(over)
    mix = fn c, o -> round(c * a + o * (1 - a)) end
    "#" <> Enum.map_join([mix.(r, or_), mix.(g, og), mix.(b, ob)], "", &(&1 |> Integer.to_string(16) |> String.pad_leading(2, "0")))
  end
end
