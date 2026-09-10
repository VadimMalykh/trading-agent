defmodule FluxTrader.Repo.Migrations.AddExchangeFieldsToPaperTrades do
  @moduledoc """
  A row that came from a real fill must say so, and must carry the ids that let it be
  reconciled against the exchange (REAL_MONEY_TRACK §2 step 3, built 2026-09-10).

  Until now the `auto` path wrote the same row as the paper path — the price the signal
  carried, the quantity the risk manager computed — and assumed the fill. With the order
  path signed, the `auto` path writes the exchange's `avgPrice` and `executedQty` instead,
  and these columns record where the numbers came from and which orders they belong to.
  """
  use Ecto.Migration

  def change do
    alter table(:paper_trades) do
      # "paper" (priced at the last trade, charged the measured crossing cost) or
      # "exchange" (real fills, charged the two taker fees only — see ExecCost).
      add :fill_source, :string, null: false, default: "paper"
      add :entry_order_id, :bigint
      add :exit_order_id, :bigint
      # The catastrophe brake RiskManager attaches on the auto path (Q2, kept 2026-09-10):
      # STOP_MARKET and TAKE_PROFIT_MARKET, closePosition. Nil on paper rows.
      add :stop_order_id, :bigint
      add :target_order_id, :bigint
      # "timer" (the scored 4h exit), "stop", "target", or "position_missing" when the
      # exchange had no position to close and no brake reported a fill.
      add :exit_reason, :string
    end

    create index(:paper_trades, [:stop_order_id])
    create index(:paper_trades, [:target_order_id])
  end
end
