defmodule Controller.Frames.Frame do
  @moduledoc """
  A frame this machine knows (`frames` table, `Controller.Repo`): where it is
  (`place`: "spool" on this machine's card, "copied" here), what state
  it's in, and what was known about it, the FITS header whole in `header`.
  """
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "frames" do
    field :place, :string, primary_key: true
    field :id, :string, primary_key: true
    field :state, :string
    field :path, :string
    field :bytes, :integer
    field :sha256, :string
    field :put_at_ms, :integer
    field :seq, :integer
    field :taken_at, :utc_datetime_usec
    field :why, :string
    field :exposure_ms, :float
    field :gain, :integer
    field :stack, :integer
    field :mode, :string
    field :background, :integer
    field :noise, :float
    field :max, :integer
    field :stars, :integer
    field :hfr_px, :float
    field :verdict, :string
    field :box, :string
    field :mount_ra_deg, :float
    field :mount_dec_deg, :float
    field :measured_stars, :integer
    field :measured_hfr_px, :float
    field :measured_verdict, :string
    field :header, :map
    timestamps(type: :utc_datetime_usec)
  end

  @fields ~w(place id state path bytes sha256 put_at_ms seq taken_at why exposure_ms gain stack mode background noise max stars hfr_px verdict box mount_ra_deg mount_dec_deg measured_stars measured_hfr_px measured_verdict header)a

  def changeset(frame, attrs), do: frame |> cast(attrs, @fields) |> validate_required([:place, :id, :state])

  @doc "Columns from a camera record (`Controller.ScopeCamera`'s), as far as it has them."
  def from_record(r) when is_map(r) do
    %{
      seq: r[:seq],
      taken_at: r[:at],
      why: r[:why],
      exposure_ms: r[:exposure_ms] && r[:exposure_ms] / 1,
      gain: r[:gain],
      stack: r[:stack],
      mode: r[:mode],
      background: r[:background],
      noise: r[:noise],
      max: r[:max],
      stars: r[:stars],
      hfr_px: r[:hfr_px],
      verdict: r[:verdict] && to_string(r[:verdict])
    }
  end

  def from_record(_), do: %{}

  @doc "Columns from a FITS header (`[{keyword, value}]`)."
  def from_header(header) do
    h = Map.new(header)

    %{
      seq: h["OBS FRAME SEQ"],
      taken_at: with(s when is_binary(s) <- h["DATE-OBS"], {:ok, n} <- NaiveDateTime.from_iso8601(s), do: DateTime.from_naive!(n, "Etc/UTC"), else: (_ -> nil)),
      why: h["OBS FRAME WHY"],
      exposure_ms: is_number(h["EXPTIME"]) && h["EXPTIME"] * 1000 || nil,
      gain: h["GAIN"],
      stack: h["NCOMBINE"],
      mode: h["OBS CAMERA MODE"],
      background: h["OBS FRAME BACKGROUND"],
      noise: h["OBS FRAME NOISE"] && h["OBS FRAME NOISE"] / 1,
      max: h["OBS FRAME MAX"],
      stars: h["OBS FRAME STARS"],
      hfr_px: h["OBS FRAME HFR PX"] && h["OBS FRAME HFR PX"] / 1,
      verdict: h["OBS FRAME VERDICT"],
      box: h["OBS BOX NODE"],
      mount_ra_deg: h["OBS MOUNT START RA DEG"] && h["OBS MOUNT START RA DEG"] / 1,
      mount_dec_deg: h["OBS MOUNT START DEC DEG"] && h["OBS MOUNT START DEC DEG"] / 1,
      header: header |> Enum.reject(fn {k, _} -> k in ["COMMENT", "HISTORY", ""] end) |> Map.new()
    }
  end
end
