defmodule FluxTrader.Repo.Migrations.CreateTrades do
  use Ecto.Migration

  def change do
    create table(:trades) do
      add :position_id, references(:positions, on_delete: :nothing), null: false
      add :symbol, :string, null: false
      add :side, :string, null: false
      add :price, :float, null: false
      add :quantity, :float, null: false
      add :fee, :float
      add :order_id, :string
      add :executed_at, :utc_datetime_usec, null: false

      timestamps()
    end

    create index(:trades, [:position_id])
    create index(:trades, [:symbol])
    create index(:trades, [:executed_at])
  end
end
