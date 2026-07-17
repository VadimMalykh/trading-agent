defmodule FluxTrader.Repo.Migrations.CreateCandles do
  use Ecto.Migration

  def change do
    create table(:candles, primary_key: false) do
      add :symbol, :string, null: false
      add :interval, :string, null: false
      add :open_time, :utc_datetime_usec, null: false
      add :open, :float, null: false
      add :high, :float, null: false
      add :low, :float, null: false
      add :close, :float, null: false
      add :volume, :float, null: false
      add :close_time, :utc_datetime_usec, null: false
    end

    create unique_index(:candles, [:symbol, :interval, :open_time])
    create index(:candles, [:symbol])
    create index(:candles, [:open_time])
  end
end
