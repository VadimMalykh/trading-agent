defmodule FluxTrader.Repo.Migrations.CreateAppSettings do
  use Ecto.Migration

  def change do
    create table(:app_settings, primary_key: false) do
      add :key, :string, primary_key: true
      add :value, :map, null: false, default: %{}
      timestamps(type: :utc_datetime_usec)
    end
  end
end
