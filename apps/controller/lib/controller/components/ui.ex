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
    <main id={@id} class={["page", @class, @night && "night"]} {@rest}>
      <header :if={@header != []} class="page-header">{render_slot(@header)}</header>
      {render_slot(@inner_block)}
    </main>
    """
  end

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

  def help(assigns) do
    ~H"""
    <.link href={@href} class="help" aria-label="help">?</.link>
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
  slot :inner_block, required: true

  def hint(assigns) do
    ~H"""
    <p class={["hint", @class]}>{render_slot(@inner_block)}</p>
    """
  end

  @doc """
  A button, or a link that looks like one. `variant`: default, primary, danger, ghost.
  """
  attr :navigate, :string, default: nil
  attr :href, :string, default: nil
  attr :variant, :string, default: "default"
  attr :on, :boolean, default: false
  attr :class, :string, default: nil
  attr :rest, :global, include: ~w(phx-click phx-value-port phx-value-what phx-value-axis phx-value-sign phx-value-deg phx-value-mode phx-value-rate phx-value-id disabled type data-confirm phx-hook form)
  slot :inner_block, required: true

  def btn(assigns) do
    ~H"""
    <.link :if={@navigate || @href} navigate={@navigate} href={@href} class={["btn", "btn-#{@variant}", @on && "on", @class]}>
      {render_slot(@inner_block)}
    </.link>
    <button :if={!(@navigate || @href)} class={["btn", "btn-#{@variant}", @on && "on", @class]} {@rest}>
      {render_slot(@inner_block)}
    </button>
    """
  end
end
