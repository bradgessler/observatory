defmodule Controller.Sky.Solve do
  @moduledoc """
  Plate solving: hand it a photo of the sky, get back where it points.

  First implementation talks to nova.astrometry.net (free, needs an API key in
  `NOVA_API_KEY` or `config :controller, :nova_api_key`). A local solver
  (ASTAP / astrometry.net) slots in behind the same function later (#10).

  Returns `{:ok, %{ra_deg, dec_deg, radius_deg, pixscale_arcsec, orientation_deg, parity, width, height}}`.
  """
  @base "https://nova.astrometry.net/api"
  @poll_ms 5_000
  @max_wait_ms 240_000

  def configured?, do: api_key() != nil

  def solve(path, opts \\ []) do
    with {:ok, key} <- fetch_key(),
         {:ok, session} <- login(key),
         {:ok, subid} <- upload(session, path, opts),
         {:ok, jobid} <- wait_for_job(subid, System.monotonic_time(:millisecond) + @max_wait_ms),
         {:ok, cal} <- wait_for_calibration(jobid, System.monotonic_time(:millisecond) + @max_wait_ms) do
      {:ok, cal}
    end
  end

  defp fetch_key do
    case api_key() do
      nil -> {:error, :no_api_key}
      key -> {:ok, key}
    end
  end

  defp api_key,
    do: System.get_env("NOVA_API_KEY") || Application.get_env(:controller, :nova_api_key)

  defp login(key) do
    case Req.post("#{@base}/login", form: [{"request-json", Jason.encode!(%{apikey: key})}]) do
      {:ok, %{body: %{"status" => "success", "session" => s}}} -> {:ok, s}
      {:ok, %{body: body}} -> {:error, {:login, body}}
      {:error, e} -> {:error, {:login, e}}
    end
  end

  defp upload(session, path, opts) do
    params = %{
      session: session,
      publicly_visible: "n",
      allow_modifications: "d",
      allow_commercial_use: "d",
      # a phone's wide camera is roughly 60-80 degrees across; tell the solver
      scale_units: "degwidth",
      scale_lower: Keyword.get(opts, :scale_lower, 30),
      scale_upper: Keyword.get(opts, :scale_upper, 100),
      downsample_factor: 2
    }

    content_type = if String.ends_with?(String.downcase(path), ".png"), do: "image/png", else: "image/jpeg"

    multipart =
      Req.new(url: "#{@base}/upload", receive_timeout: 120_000)
      |> Req.merge(
        form_multipart: [
          {"request-json", Jason.encode!(params)},
          {"file", {File.read!(path), filename: Path.basename(path), content_type: content_type}}
        ]
      )

    case Req.post(multipart) do
      {:ok, %{body: %{"status" => "success", "subid" => id}}} -> {:ok, id}
      {:ok, %{body: body}} -> {:error, {:upload, body}}
      {:error, e} -> {:error, {:upload, e}}
    end
  end

  defp wait_for_job(subid, deadline) do
    case Req.get("#{@base}/submissions/#{subid}") do
      {:ok, %{body: %{"jobs" => [job | _]}}} when is_integer(job) ->
        {:ok, job}

      _ ->
        if System.monotonic_time(:millisecond) > deadline do
          {:error, :timeout_waiting_for_job}
        else
          Process.sleep(@poll_ms)
          wait_for_job(subid, deadline)
        end
    end
  end

  defp wait_for_calibration(jobid, deadline) do
    case Req.get("#{@base}/jobs/#{jobid}") do
      {:ok, %{body: %{"status" => "success"}}} ->
        {:ok, %{body: c}} = Req.get("#{@base}/jobs/#{jobid}/calibration")
        {:ok, %{body: info}} = Req.get("#{@base}/jobs/#{jobid}/info")

        {:ok,
         %{
           ra_deg: c["ra"],
           dec_deg: c["dec"],
           radius_deg: c["radius"],
           pixscale_arcsec: c["pixscale"],
           orientation_deg: c["orientation"],
           parity: c["parity"],
           width: get_in(info, ["calibration", "width_arcsec"]),
           height: get_in(info, ["calibration", "height_arcsec"]),
           objects: info["objects_in_field"] || []
         }}

      {:ok, %{body: %{"status" => "failure"}}} ->
        {:error, :solve_failed}

      _ ->
        if System.monotonic_time(:millisecond) > deadline do
          {:error, :timeout_solving}
        else
          Process.sleep(@poll_ms)
          wait_for_calibration(jobid, deadline)
        end
    end
  end
end
