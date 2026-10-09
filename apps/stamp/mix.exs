defmodule Stamp.MixProject do
  use Mix.Project

  def project do
    [
      app: :stamp,
      version: "0.1.0",
      build_path: "../../_build",
      config_path: "../../config/config.exs",
      deps_path: "../../deps",
      lockfile: "../../mix.lock",
      elixir: "~> 1.15",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application, do: [extra_applications: [:logger]]

  # The Stamp a Box pages: the controller's UI over the provision plumbing.
  # The stamping Mac's build plugs them into the controller (config :controller,
  # :extensions); a stamped box never compiles them, so they are not in its
  # image at all.
  defp deps do
    [
      {:controller, in_umbrella: true},
      {:provision, in_umbrella: true},
      {:lazy_html, ">= 0.1.0", only: :test}
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]
end
