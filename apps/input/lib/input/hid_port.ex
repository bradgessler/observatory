defmodule Input.HIDPort do
  @moduledoc """
  The thin edge to `priv/hidport` (C, libhidapi). Two calls: list every HID
  device the OS sees, and open one as an Erlang port that streams raw input
  reports back as messages. Everything above this is plain Elixir.
  """

  @type device :: %{
          vendor_id: integer,
          product_id: integer,
          usage_page: integer,
          usage: integer,
          path: String.t(),
          manufacturer: String.t(),
          product: String.t()
        }

  def executable, do: Path.join(:code.priv_dir(:input), "hidport")

  @doc "Every HID device on this machine."
  @spec list() :: [device]
  def list do
    case System.cmd(executable(), ["list"], stderr_to_stdout: true) do
      {out, 0} ->
        out
        |> String.split("\n", trim: true)
        |> Enum.flat_map(fn
          "L " <> rest -> [parse_line(rest)]
          _ -> []
        end)
        |> Enum.reject(&is_nil/1)

      {out, _} ->
        require Logger
        Logger.warning("hidport list failed: #{String.trim(out)}")
        []
    end
  rescue
    e in ErlangError ->
      require Logger
      Logger.warning("hidport missing or not executable: #{inspect(e)}")
      []
  end

  defp parse_line(rest) do
    case String.split(rest, "\t") do
      [head | names] ->
        case String.split(head, " ", parts: 5) do
          [vid, pid, up, u, path] ->
            %{
              vendor_id: String.to_integer(vid, 16),
              product_id: String.to_integer(pid, 16),
              usage_page: String.to_integer(up, 16),
              usage: String.to_integer(u, 16),
              path: path,
              manufacturer: Enum.at(names, 0, "") |> String.trim(),
              product: Enum.at(names, 1, "") |> String.trim()
            }

          _ ->
            nil
        end

      _ ->
        nil
    end
  end

  @doc """
  Open a device. The calling process receives `{port, {:data, {:eol, line}}}`
  messages: `"O <path>"` once, then `"R <hex>"` per report, `"E <why>"` on
  error. Closing the port (or the owner dying) ends the C process.
  """
  def open(path) do
    Port.open({:spawn_executable, executable()}, [:binary, :exit_status, {:line, 512}, args: ["open", path]])
  end
end
