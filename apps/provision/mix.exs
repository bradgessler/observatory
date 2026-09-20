defmodule Provision.MixProject do
  use Mix.Project

  def project do
    [
      app: :provision,
      version: "0.1.0",
      build_path: "../../_build",
      config_path: "../../config/config.exs",
      deps_path: "../../deps",
      lockfile: "../../mix.lock",
      elixir: "~> 1.15",
      start_permanent: Mix.env() == :prod,
      # the VM smoke test needs qemu and a built image; it is opt in
      test_coverage: [ignore_modules: [Provision.VM]],
      deps: deps()
    ]
  end

  def application do
    [
      extra_applications: [:logger],
      mod: {Provision.Application, []}
    ]
  end

  # Nothing but the plumbing: this app shells out to fwup and mix, and says
  # what it is doing on a PubSub topic. It must stay liftable out of here.
  defp deps do
    [{:telescope, in_umbrella: true}]
  end
end
