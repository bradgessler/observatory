defmodule Controller.Components.UI do
  @moduledoc """
  The handful of pieces every page is built from, so pages line up on the same
  grid and change together. See DESIGN.md.

      <.page id="setup" night={@night}>
        <:header>
          <.back navigate={~p"/"} label="keypad" />
          <.title>eq6r · setup</.title>
          <:actions><.help href={~p"/docs/keypad"} /></:actions>
        </:header>
        <.card title="Home"> … </.card>
      </.page>
  """
  use Phoenix.Component

  # -- page & header --------------------------------------------------------------

  attr :id, :string, required: true
  attr :night, :boolean, default: false
  attr :class, :string, default: nil
  attr :rest, :global
  slot :header
  slot :inner_block, required: true

  def page(assigns) do
    ~H"""
    <.wrap nested={@class && String.contains?(to_string(@class), "nested")} id={@id} class={["page", @class, @night && "night"]} {@rest}>
      <header :if={@header != []} class="page-header">{render_slot(@header)}</header>
      <.skip_target :if={!(@class && String.contains?(to_string(@class), "nested"))} />
      {render_slot(@inner_block)}
    </.wrap>
    """
  end

  @doc """
  Where the skip link lands: just past the header, before the first thing on
  the page. Once per document, so a nested page never renders one.
  """
  def skip_target(assigns) do
    ~H"""
    <span id="content" tabindex="-1" class="skip-target"></span>
    """
  end

  # one <main> per document: a page nested in another renders as a plain block
  attr :nested, :boolean, default: false
  attr :rest, :global
  slot :inner_block, required: true

  defp wrap(%{nested: true} = assigns), do: ~H"<div {@rest}>{render_slot(@inner_block)}</div>"
  defp wrap(assigns), do: ~H"<main {@rest}>{render_slot(@inner_block)}</main>"

  attr :navigate, :string, required: true
  attr :label, :string, required: true

  def back(assigns) do
    ~H"""
    <.link navigate={@navigate} class="back">‹ {@label}</.link>
    """
  end

  slot :inner_block, required: true

  def title(assigns) do
    ~H"""
    <h1 class="page-title">{render_slot(@inner_block)}</h1>
    """
  end

  slot :inner_block, required: true

  def actions(assigns) do
    ~H"""
    <span class="actions">{render_slot(@inner_block)}</span>
    """
  end

  attr :href, :string, required: true
  attr :label, :string, default: nil, doc: "what the help is about; defaults to the doc's slug"

  def help(assigns) do
    assigns = assign_new(assigns, :name, fn -> "help: " <> (assigns.label || Path.basename(assigns.href)) end)

    ~H"""
    <.link href={@href} class="help help-icon" aria-label={@name}>?</.link>
    """
  end

  # -- containers -------------------------------------------------------------------

  attr :title, :string, default: nil
  attr :class, :string, default: nil
  attr :rest, :global
  slot :aside
  slot :inner_block, required: true

  def card(assigns) do
    ~H"""
    <section class={["card", @class]} {@rest}>
      <div :if={@title || @aside != []} class="card-head">
        <h2 :if={@title} class="card-title">{@title}</h2>
        <span :if={@aside != []} class="card-aside">{render_slot(@aside)}</span>
      </div>
      {render_slot(@inner_block)}
    </section>
    """
  end

  @doc "Equal-width controls in a row; wraps on narrow screens."
  attr :class, :string, default: nil
  slot :inner_block, required: true

  def row(assigns) do
    ~H"""
    <div class={["row", @class]}>{render_slot(@inner_block)}</div>
    """
  end

  @doc "Key on the left, value on the right, optional control at the end."
  attr :label, :string, required: true
  attr :value, :string, default: nil
  slot :inner_block

  def kv(assigns) do
    ~H"""
    <div class="kv">
      <span class="kv-k">{@label}</span>
      <span class="kv-v">{@value}{render_slot(@inner_block)}</span>
    </div>
    """
  end

  @doc "A setting with its current value and one action."
  attr :label, :string, required: true
  attr :value, :string, required: true
  slot :inner_block

  def setting(assigns) do
    ~H"""
    <div class="setting">
      <div class="setting-text"><strong>{@label}</strong><span>{@value}</span></div>
      <span class="setting-action">{render_slot(@inner_block)}</span>
    </div>
    """
  end

  # -- small things ------------------------------------------------------------------

  attr :on, :boolean, default: false
  attr :warn, :boolean, default: false
  attr :dim, :boolean, default: false
  slot :inner_block, required: true

  def badge(assigns) do
    ~H"""
    <span class={["badge", @on && "on", @warn && "warn", @dim && "dim"]}>{render_slot(@inner_block)}</span>
    """
  end

  attr :class, :string, default: nil
  attr :rest, :global
  slot :inner_block, required: true

  def hint(assigns) do
    ~H"""
    <p class={["hint", @class]} {@rest}>{render_slot(@inner_block)}</p>
    """
  end

  @doc """
  A button, or a link that looks like one. `variant`: default, primary, danger, ghost.
  """
  attr :navigate, :string, default: nil
  attr :patch, :string, default: nil
  attr :href, :string, default: nil
  attr :variant, :string, default: "default"
  attr :on, :boolean, default: false
  attr :class, :string, default: nil
  # phx-value-* are NOT global attributes: every one a caller uses must be listed here or it is silently dropped
  attr :rest, :global, include: ~w(data-confirm disabled form phx-click phx-hook phx-value-axis phx-value-az phx-value-deg phx-value-dir phx-value-fps phx-value-i phx-value-id phx-value-m phx-value-mode phx-value-name phx-value-on phx-value-port phx-value-q phx-value-rate phx-value-sign phx-value-tab phx-value-what type)
  slot :inner_block, required: true

  def btn(assigns) do
    ~H"""
    <.link :if={@navigate || @href || @patch} navigate={@navigate} patch={@patch} href={@href} class={["btn", "btn-#{@variant}", @on && "on", @class]} {@rest}>
      {render_slot(@inner_block)}
    </.link>
    <button :if={!(@navigate || @href || @patch)} class={["btn", "btn-#{@variant}", @on && "on", @class]} {@rest}>
      {render_slot(@inner_block)}
    </button>
    """
  end

  @doc "STOP, the one loud key: in a header (`mini`) or full width (`bar`)."
  attr :click, :string, default: "stop"
  attr :size, :string, default: "mini"

  def stop(assigns) do
    ~H"""
    <button class={if @size == "bar", do: "stop-bar", else: "stop-mini"} phx-click={@click} aria-label="stop the mount">STOP</button>
    """
  end

  @doc """
  A quiet line at the bottom that fades on its own. `notice` is nil, a string,
  or `{text, key}` when the same words must show again.
  """
  attr :notice, :any, default: nil

  def notice(%{notice: {text, key}} = assigns), do: notice(assign(assigns, notice: text, key: key))

  def notice(assigns) do
    assigns = assign_new(assigns, :key, fn -> :erlang.phash2(assigns.notice) end)

    ~H"""
    <p :if={@notice} id={"notice-#{@key}"} class="notice" role="status" aria-live="polite">{@notice}</p>
    """
  end

  @doc """
  A segmented control: a sunk trough of keys, exactly one lit. You always see
  which state you are in. Each `:opt` names its click event and the
  `phx-value-*` pairs it sends.

      <.seg label="timed stills">
        <:opt on={!@on} click="timed" value={%{on: "false"}}>Off</:opt>
        <:opt on={@on} click="timed" value={%{on: "true"}}>Every 5 s</:opt>
      </.seg>
  """
  attr :label, :string, required: true
  attr :class, :string, default: nil

  slot :opt, required: true do
    attr :on, :boolean
    attr :click, :string, required: true
    attr :value, :map
    attr :disabled, :boolean
    attr :live, :boolean, doc: "this choice makes the scope move by itself: lit in the warn tone"
  end

  def seg(assigns) do
    ~H"""
    <div class={["seg", "seg-#{length(@opt)}", @class]} role="radiogroup" aria-label={@label}>
      <button
        :for={o <- @opt}
        class={["seg-opt", o[:live] && "seg-live", o[:on] && "on"]}
        phx-click={o.click}
        {values(o[:value])}
        role="radio"
        aria-checked={to_string(o[:on] == true)}
        disabled={o[:disabled]}
      >
        {render_slot(o)}
      </button>
    </div>
    """
  end

  defp values(nil), do: %{}
  defp values(map), do: Map.new(map, fn {k, v} -> {"phx-value-#{k}", v} end)

  @doc "One row in a list: a name, a dim detail under it, and the keys that act on it. Inside `<.items>` it is a list item."
  attr :label, :string, required: true
  attr :detail, :string, default: nil
  attr :as, :string, default: "div", doc: "\"li\" inside an <.items> list"
  attr :rest, :global
  slot :inner_block

  def item(assigns) do
    ~H"""
    <.dynamic_tag tag_name={@as} class="item" {@rest}>
      <div class="item-text"><strong>{@label}</strong><span :if={@detail} class="dim">{@detail}</span></div>
      {render_slot(@inner_block)}
    </.dynamic_tag>
    """
  end

  @doc "A list of `<.item as=\"li\">` rows: a real list, so its length and position are announced."
  attr :label, :string, default: nil
  attr :class, :string, default: nil
  slot :inner_block, required: true

  def items(assigns) do
    ~H"""
    <ul class={["items", @class]} role="list" aria-label={@label}>{render_slot(@inner_block)}</ul>
    """
  end

  @doc """
  A row of rate or step keys, exactly one chosen: a radio group, like `seg`,
  in the keypad's larger key shape.

      <.rates label="slew rate" class="rates-4">
        <:opt :for={r <- @rates} on={r == @rate} click="rate" value={%{rate: r}}>{r}×</:opt>
      </.rates>
  """
  attr :label, :string, required: true
  attr :class, :string, default: nil

  slot :opt, required: true do
    attr :on, :boolean
    attr :click, :string, required: true
    attr :value, :map
  end

  def rates(assigns) do
    ~H"""
    <div class={["rates", @class]} role="radiogroup" aria-label={@label}>
      <button :for={o <- @opt} class={["rate", o[:on] && "on"]} phx-click={o.click} {values(o[:value])} role="radio" aria-checked={to_string(o[:on] == true)}>
        {render_slot(o)}
      </button>
    </div>
    """
  end

  @doc "A running/still lamp with words for a screen reader; the glow carries it for eyes."
  attr :on, :boolean, default: false
  attr :class, :string, default: nil

  def lamp(assigns) do
    ~H"""
    <i class={["dot", @on && "on", @class]} role="img" aria-label={if @on, do: "moving", else: "still"}></i>
    """
  end
end
