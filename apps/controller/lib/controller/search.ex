defmodule Controller.Search do
  @moduledoc """
  Finding a page by typing a bit of its name: every page in `Controller.Nav`
  (its title, its group, its one line), the pages under them that aren't in
  the sidebar (a camera's Settings and Frames), and every doc in
  `priv/docs` (its title and headings).

      Search.find("cam set")
      # => [%{title: "Settings", where: "Telescope Camera", path: "/cameras/telescope/settings", ...}, ...]

  **Matching.** The query is split into words and every word has to match
  somewhere. A word that starts a word of the title counts most, then one
  inside the title, then the group or parent page, then the one line and a
  doc's headings, and last a word anywhere in a doc ("plate" finds the help
  that explains plate solving); ties go to pages over docs, then the order
  of the sidebar.
  A single word that matches nothing whole still finds a title whose letters
  it has in order ("tlscp" finds Telescope Camera), ranked last.

  `find("")` is the starting list: the help for the page you're on first,
  then every page in sidebar order, so on a phone it doubles as the menu.
  """
  use Controller, :verified_routes

  @limit 12

  @doc "The results for `query`, best first; with `here:` (the current path), an empty query starts with that page's help."
  def find(query, opts \\ []) do
    case words(query) do
      [] -> start(Keyword.get(opts, :here))
      ws -> index() |> Enum.flat_map(&score(&1, ws, query)) |> Enum.sort_by(fn {s, item} -> {-s, item.rank} end) |> Enum.map(&elem(&1, 1)) |> Enum.take(@limit)
    end
  end

  defp start(here) do
    pages = Enum.filter(index(), &(&1.kind == :page))

    help =
      with path when is_binary(path) <- Controller.Nav.current(here),
           %{doc: doc, title: title} when is_binary(doc) <- Enum.find(pages, &(&1.path == path)) do
        [%{kind: :doc, title: "Help: #{title}", where: "About this page", path: doc, icon: "help", rank: -1}]
      else
        _ -> []
      end

    help ++ pages
  end

  @doc "Everything that can be found, in sidebar order: pages, the pages under them, docs."
  def index do
    pages = for {group, _blurb, pages} <- Controller.Nav.groups(), p <- pages, do: Map.merge(p, %{kind: :page, where: group})
    under = for p <- Controller.Nav.under(), do: Map.merge(p, %{kind: :page, where: p.parent})

    (pages ++ under ++ docs())
    |> Enum.with_index()
    |> Enum.map(fn {item, i} -> Map.put(item, :rank, i) end)
  end

  # the docs, read once and kept: their titles and headings change only with a new build
  defp docs do
    case :persistent_term.get({__MODULE__, :docs}, nil) do
      nil ->
        docs = read_docs()
        :persistent_term.put({__MODULE__, :docs}, docs)
        docs

      docs ->
        docs
    end
  end

  defp read_docs do
    dir = :code.priv_dir(:controller) |> Path.join("docs")

    for file <- dir |> File.ls!() |> Enum.sort(), String.ends_with?(file, ".md") do
      md = dir |> Path.join(file) |> File.read!()
      lines = String.split(md, "\n")
      title = lines |> hd() |> String.trim_leading("# ") |> String.trim()
      headings = for "#" <> _ = l <- tl(lines), do: l |> String.trim_leading("#") |> String.trim()
      slug = Path.rootname(file)
      # every word in it once, for the last resort: a word only the text has
      body = md |> words() |> Enum.filter(&(String.length(&1) >= 3)) |> Enum.uniq()
      %{kind: :doc, title: title, where: "Help", line: Enum.join(headings, " · "), body: body, path: ~p"/docs/#{slug}", icon: "help"}
    end
  rescue
    _ -> []
  end

  defp words(query), do: query |> to_string() |> String.downcase() |> String.split(~r/[^\p{L}\p{N}]+/u, trim: true)

  defp score(item, ws, query) do
    title = words(item.title)
    where = words(item.where)
    line = words(item[:line])
    kind = if item.kind == :page, do: 0.5, else: 0

    scores =
      Enum.map(ws, fn w ->
        cond do
          Enum.any?(title, &String.starts_with?(&1, w)) -> 6
          Enum.any?(title, &String.contains?(&1, w)) -> 4
          Enum.any?(where, &String.starts_with?(&1, w)) -> 3
          Enum.any?(line, &String.starts_with?(&1, w)) -> 1
          Enum.any?(item[:body] || [], &String.starts_with?(&1, w)) -> 0.25
          true -> nil
        end
      end)

    cond do
      Enum.all?(scores, & &1) -> [{Enum.sum(scores) + kind, item}]
      length(ws) == 1 and in_order?(String.downcase(item.title), String.downcase(String.trim(query))) -> [{0.5 + kind, item}]
      true -> []
    end
  end

  # every letter of the query, in order, somewhere in the title
  defp in_order?(_, ""), do: true
  defp in_order?("", _), do: false
  defp in_order?(<<c::utf8, t::binary>>, <<c::utf8, q::binary>>), do: in_order?(t, q)
  defp in_order?(<<_::utf8, t::binary>>, q), do: in_order?(t, q)
end
