defmodule Controller.Repo.Migrations.CreateFrames do
  use Ecto.Migration

  # Every frame this machine knows: on a box, the ones on its card (the spool's
  # index: waiting, leased, copied); on the Mac, the ones copied to it, with
  # their FITS header. The pictures themselves are files.
  def change do
    create table(:frames, primary_key: false) do
      # "spool" (on this machine's card, waiting for the Mac) or "copied" (copied here)
      add :place, :string, null: false
      # the file's name: milliseconds since 1970, a counter, ".fits"
      add :id, :string, null: false
      # spool: ready, leased, sent; copied: copied, measured
      add :state, :string, null: false
      add :path, :string
      add :bytes, :integer
      add :sha256, :string
      add :put_at_ms, :bigint

      # from the camera's record and the header
      add :seq, :integer
      add :taken_at, :utc_datetime_usec
      add :why, :string
      add :exposure_ms, :float
      add :gain, :integer
      add :stack, :integer
      add :mode, :string
      add :background, :integer
      add :noise, :float
      add :max, :integer
      add :stars, :integer
      add :hfr_px, :float
      add :verdict, :string
      add :box, :string
      add :mount_ra_deg, :float
      add :mount_dec_deg, :float

      # measured again where it was copied
      add :measured_stars, :integer
      add :measured_hfr_px, :float
      add :measured_verdict, :string

      # the whole FITS header, keyword to value, for anything not in a column (json_extract)
      add :header, :map

      timestamps(type: :utc_datetime_usec)
    end

    create unique_index(:frames, [:place, :id])
    create index(:frames, [:place, :state])
    create index(:frames, [:taken_at])
    create index(:frames, [:seq])
  end
end
