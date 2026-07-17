defmodule FluxTrader.Repo.Migrations.CreateMarketDataTables do
  use Ecto.Migration

  def change do
    create table(:market_trades, primary_key: false) do
      add :symbol, :string, null: false
      add :window_start, :utc_datetime_usec, null: false
      add :trade_count, :integer, null: false, default: 0
      add :volume, :float, null: false, default: 0.0
      add :buy_volume, :float, null: false, default: 0.0
      add :sell_volume, :float, null: false, default: 0.0
      add :vwap, :float
      add :high, :float
      add :low, :float
    end

    create unique_index(:market_trades, [:symbol, :window_start])
    create index(:market_trades, [:symbol])
    create index(:market_trades, [:window_start])

    create table(:orderbook_snapshots, primary_key: false) do
      add :symbol, :string, null: false
      add :ts, :utc_datetime_usec, null: false
      add :mid, :float, null: false
      add :spread, :float, null: false
      add :microprice, :float
      add :bid_volume, :float, null: false
      add :ask_volume, :float, null: false
      add :imbalance, :float, null: false
      add :bid_depth_near, :float
      add :ask_depth_near, :float
      add :bid_depth_far, :float
      add :ask_depth_far, :float
    end

    create unique_index(:orderbook_snapshots, [:symbol, :ts])
    create index(:orderbook_snapshots, [:symbol])
    create index(:orderbook_snapshots, [:ts])

    create table(:funding_rates, primary_key: false) do
      add :symbol, :string, null: false
      add :ts, :utc_datetime_usec, null: false
      add :mark_price, :float
      add :index_price, :float
      add :last_funding_rate, :float
      add :next_funding_time, :utc_datetime_usec
    end

    create unique_index(:funding_rates, [:symbol, :ts])
    create index(:funding_rates, [:symbol])

    create table(:open_interest, primary_key: false) do
      add :symbol, :string, null: false
      add :ts, :utc_datetime_usec, null: false
      add :open_interest, :float, null: false
    end

    create unique_index(:open_interest, [:symbol, :ts])
    create index(:open_interest, [:symbol])

    create table(:liquidations, primary_key: false) do
      add :symbol, :string, null: false
      add :ts, :utc_datetime_usec, null: false
      add :side, :string
      add :price, :float
      add :quantity, :float
      add :order_id, :string
    end

    create index(:liquidations, [:symbol, :ts])
    create index(:liquidations, [:ts])
  end
end
