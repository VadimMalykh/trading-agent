defmodule FluxTrader.Repo.Migrations.CreateAccountFillsAndIncome do
  @moduledoc """
  The account page (2026-11-10): the USDⓈ-M account is shared by the live pilot and Vadim's
  manual trades (Binance gives this account no sub-accounts). `FluxTrader.Account.Sync` copies
  every fill (`/fapi/v1/userTrades`) and every income row (`/fapi/v1/income`) here, so the
  page can rebuild flat-to-flat deals per symbol and split them bot / manual by order id.
  """
  use Ecto.Migration

  def change do
    create table(:account_fills) do
      add :symbol, :string, null: false
      add :trade_id, :bigint, null: false
      add :order_id, :bigint, null: false
      add :side, :string, null: false
      add :qty, :float, null: false
      add :price, :float, null: false
      add :realized_pnl, :float, null: false
      add :commission, :float, null: false
      add :commission_asset, :string, null: false
      add :maker, :boolean
      add :time, :utc_datetime_usec, null: false
      timestamps()
    end

    create unique_index(:account_fills, [:symbol, :trade_id])
    create index(:account_fills, [:time])

    create table(:account_income) do
      add :symbol, :string
      add :income_type, :string, null: false
      add :income, :float, null: false
      add :asset, :string, null: false
      add :tran_id, :bigint, null: false
      add :trade_id, :string
      add :time, :utc_datetime_usec, null: false
      timestamps()
    end

    # A funding settlement shares one tranId across symbols on some accounts, so the key is
    # the whole identity, not tranId alone.
    create unique_index(:account_income, [:tran_id, :income_type, :symbol, :time],
             name: :account_income_identity
           )

    create index(:account_income, [:time])
  end
end
