defmodule Queues.MixProject do
  use Mix.Project

  def project do
    [
      app: :queues,
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
      extra_applications: [:logger, :crypto],
      mod: {Queues.Application, []}
    ]
  end

  defp deps do
    [
      # every queue's numbers go out on the cluster's PubSub, so one page sees every machine's
      {:telescope, in_umbrella: true},
      {:telemetry, "~> 1.0"}
    ]
  end
end
