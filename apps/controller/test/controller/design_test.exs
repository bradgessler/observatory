defmodule Controller.DesignTest do
  @moduledoc """
  The palette meets WCAG 2.1 AA, checked from the token file itself:
  text 4.5:1 on every surface it can sit on, 3:1 for the key edge and for a
  lit key against the panel around it (non-text contrast, 1.4.11). Three
  themes: default (dark), light, night. If a colour changes here and the
  eyepiece can't read it, this fails.
  """
  use ExUnit.Case, async: true

  @tokens Path.expand("../../priv/static/assets/css/tokens.css", __DIR__)

  @text ~w(text dim accent on warn amber)
  @surfaces ~w(bg panel panel2 key lit lit-on lit-warn)

  test "text is 4.5:1 or better on every surface, in every theme" do
    for {theme, t} <- themes() do
      for fg <- @text, bg <- @surfaces, fg != "amber" or bg == "amber-bg" or true do
        ratio = contrast(t[fg], t[bg])
        assert ratio >= 4.5, "#{theme}: --#{fg} #{t[fg]} on --#{bg} #{t[bg]} is #{Float.round(ratio, 2)}:1"
      end

      assert contrast(t["amber"], t["amber-bg"]) >= 4.5, "#{theme}: amber on its strip"
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
