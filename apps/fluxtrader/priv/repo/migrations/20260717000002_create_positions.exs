defmodule FluxTrader.Repo.Migrations.CreatePositions do
  use Ecto.Migration

  def change do
    create table(:positions) do
      add :symbol, :string, null: false
      add :side, :string, null: false
      add :entry_price, :float, null: false
      add :quantity, :float, null: false
      add :leverage, :integer, default: 1
      add :stop_loss, :float
      add :take_profit, :float
      add :status, :string, default: "open"
      add :pnl, :float, default: 0.0
      add :opened_at, :utc_datetime_usec, null: false
      add :closed_at, :utc_datetime_usec

      timestamps()
    end

    create index(:positions, [:symbol])
    create index(:positions, [:status])
    create index(:positions, [:opened_at])
  end
end
