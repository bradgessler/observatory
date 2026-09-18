defmodule Mount.MixProject do
  use Mix.Project

  def project do
    [
      app: :mount,
      version: "0.1.0",
      build_path: "../../_build",
      config_path: "../../config/config.exs",
      deps_path: "../../deps",
      lockfile: "../../mix.lock",
      elixir: "~> 1.15",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application do
    [
      extra_applications: [:logger],
      mod: {Mount.Application, []}
    ]
  end

  defp deps do
    [
      {:telescope, in_umbrella: true},
      {:circuits_uart, "~> 1.5"}
    ]
  end
end
