defmodule Controller.Words do
  @moduledoc """
  The words a page shows for things that are not words yet: an error reason,
  a value nobody knows, a node name, a page title with no mount. One place, so
  every page says the same thing the same way and nothing on a page is an
  atom, a tuple or `inspect/1` output. See DESIGN.md, "Copy".
  """

  @doc """
  A short plain-English line for an error reason, ready for a notice: no
  trailing period, first letter up, never a raw term.

      iex> Controller.Words.error({:error, :timeout})
      "Timed out waiting for an answer"
      iex> Controller.Words.error(:no_ffmpeg)
      "Something went wrong (no ffmpeg)"

  Takes a bare reason, `{:error, reason}`, the mount driver's `{cmd, axis,
  reason}`, a GenServer exit reason, an exception, or a string (passed
  through as a sentence). Pids, refs and structs are never shown.
  """
  def error({:error, reason}), do: error(reason)
  def error({:exit, reason}), do: error(reason)
  def error(text) when is_binary(text) and text != "", do: sentence(text)
  def error(%{__exception__: true} = e), do: e |> Exception.message() |> error()

  def error(:timeout), do: "Timed out waiting for an answer"
  def error(:not_connected), do: "Mount not connected"
  def error(:no_mount), do: "No mount"
  def error(:closed), do: "Connection closed"
  def error(:enoent), do: "Not found on this machine"
  def error(:eacces), do: "Permission denied"
  def error(:busy), do: "Busy, try again in a moment"
  def error(:limit), do: "Soft limit"
  def error(:unreachable), do: "Unreachable right now"
  def error(:noproc), do: "Not running"
  def error(:down), do: "Not running"
  def error(:running), do: "Already running"
  def error(:crashed), do: "It crashed, try again"
  def error(:not_found), do: "Not found"
  def error(:full), do: "Full, try again in a moment"
  def error(:not_homed), do: "Set home first"
  def error(:below_horizon), do: "Below the horizon"
  def error(:no_camera), do: "No camera"
  def error(:no_solver), do: "No plate solver on this machine"
  def error(:no_api_key), do: "No astrometry.net API key"
  def error(:unsupported_image), do: "Not an image it can read"
  def error(r) when r in [:no_solution, :solve_failed], do: "No match for the stars in this photo"
  def error(r) when r in [:moving, :motor_running], do: "Still moving"
  def error(:goto_not_started), do: "The mount didn't start the move, try again"
  def error(:counterweight_unknown), do: "Which side the counterweight is on is only a guess: say whether it is below or above level"

  # the mount's own replies (Mount.Protocol)
  def error(:no_response), do: "No answer from the mount"
  def error(:not_initialized), do: "The mount's motors aren't ready yet"
  def error(:driver_sleeping), do: "The mount's motors are asleep"
  def error(r) when r in [:unknown_command, :bad_length, :bad_character], do: "The mount refused the command"
  def error({:code, code}), do: "The mount refused the command (code #{code})"
  def error({:garbage, _}), do: "The mount sent a garbled reply"
  def error({:partial, _}), do: "The mount stopped answering mid-reply"
  # Mount.Server wraps a failed exchange as {cmd, axis, reason}
  def error({_cmd, axis, reason}) when axis in [:ra, :dec, :both], do: error(reason)
  # a GenServer call that exited: {reason, {GenServer, :call, args}}
  def error({reason, {mod, fun, args}}) when is_atom(mod) and is_atom(fun) and is_list(args), do: error(reason)

  def error(other) do
    case readable(other) do
      nil -> "Something went wrong"
      words -> "Something went wrong (#{words})"
    end
  end

  @doc """
  Why a mount isn't answering, said as what to check: the Devices list and a
  mount's own page use the same words.
  """
  def mount_problem({"e", :ra, :timeout}), do: "Port opened but the mount didn't answer: power? wrong jack? another program on the port?"
  def mount_problem({_, _, :timeout}), do: "The mount stopped answering"
  def mount_problem(:eacces), do: "Permission denied opening the port"
  def mount_problem(:enoent), do: "The port vanished (cable unplugged?)"
  def mount_problem(:eagain), do: "The port is busy: another program has it open"
  def mount_problem(e), do: error(e)

  @doc "The word for a value nobody knows yet, where a page would otherwise show a dash."
  def none, do: "Unknown"

  @doc """
  The host part of a node name, the way people know the machine:
  `:"telescope@observatory.local"` → `"observatory"`.
  """
  def host(node), do: node |> to_string() |> String.split("@") |> List.last() |> String.replace_suffix(".local", "")

  @doc """
  A page title for a page about one mount: `"eq6r · Nudge"`, or just
  `"Nudge"` when there is no mount, never a dangling separator.
  """
  def title(nil, name), do: name
  def title("", name), do: name
  def title(id, name), do: "#{id} · #{name}"

  @doc """
  A toolbar's overline on a page about one mount: its sidebar section and
  the mount, `"Controls · eq6r"`, so the title can be the page's name alone.
  """
  def section(section, nil), do: section
  def section(section, ""), do: section
  def section(section, id), do: "#{section} · #{id}"

  # A term as a few plain words, or nil when there is nothing a person could
  # read in it (pids, refs, maps, structs).
  defp readable(a) when is_atom(a) and a not in [nil, true, false], do: a |> Atom.to_string() |> String.replace("_", " ")
  defp readable(s) when is_binary(s), do: if(String.printable?(s) and s != "", do: s)
  defp readable(n) when is_number(n), do: to_string(n)
  defp readable(t) when is_tuple(t), do: t |> Tuple.to_list() |> readable_join(" ")

  defp readable(l) when is_list(l) do
    if l != [] and List.ascii_printable?(l), do: to_string(l), else: readable_join(l, ", ")
  end

  defp readable(_), do: nil

  defp readable_join(terms, sep) do
    case terms |> Enum.map(&readable/1) |> Enum.reject(&(&1 in [nil, ""])) do
      [] -> nil
      words -> Enum.join(words, sep)
    end
  end

  defp sentence(text), do: String.upcase(String.first(text)) <> String.slice(text, 1..-1//1)
end
