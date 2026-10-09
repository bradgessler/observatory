defmodule Controller.Repo.Migrations.CreateSettings do
  use Ecto.Migration

  # what used to be ~/.observatory/settings.json: a row per key, the value as JSON
  def change do
    create table(:settings, primary_key: false) do
      add :key, :string, primary_key: true
      add :value, :text, null: false
      timestamps(type: :utc_datetime_usec)
    end
  end
end
