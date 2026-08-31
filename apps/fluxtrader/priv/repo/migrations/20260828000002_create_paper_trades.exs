defmodule FluxTrader.Repo.Migrations.CreatePaperTrades do
  @moduledoc """
  The paper ledger for the A/B of M3_PLAN §2 M3-5 item 4: signal-only against signal+policy.

  Both arms run at once on the same bars, hold for the same four hours, and are charged the
  same measured crossing cost, so the only thing separating the two ledgers is coverage
  selection and regime sizing — which is precisely what the policy claims to add. `arm`
  keys the two apart.

  Columns mirror `ml/train/m3/backtest.py`'s trade frame so the live numbers can be scored
  by the same arithmetic as the backtest ones (M3_PROTOCOL §4) without a translation step.
  """
  use Ecto.Migration

  def change do
    create table(:paper_trades) do
      # "policy" | "flat_size"  (was "signal_only" until the 2026-08-31 re-registration;
      # not migrated, because the table is truncated in the same deploy)
      add :arm, :string, null: false
      add :pair, :string, null: false
      add :side, :integer, null: false
      # 1/3 .. 5/3 on the policy arm, always 1.0 on the control.
      add :size, :float, null: false, default: 1.0
      add :entry_ts, :utc_datetime, null: false
      # When the 4h hold expires. Set at entry so a restart can still close the position.
      add :exit_after_ts, :utc_datetime, null: false
      add :exit_ts, :utc_datetime
      add :entry_price, :float, null: false
      add :exit_price, :float
      # The quantity RiskManager approved, in base units. Only the `auto` path uses it (to
      # close reduce-only with the size it actually opened); the paper arms work in bps.
      add :quantity, :float
      # Notional RiskManager approved, in quote currency. The paper arms are scored in bps,
      # but the daily-loss limit is a money limit, so realised P&L has to be convertible.
      add :notional, :float
      # Booked exactly as backtest.py does: signed_ret = side * fwd_ret * size, in bps;
      # net = gross - cost_bps * size, with cost_bps the pair's measured round trip.
      add :gross_bps, :float
      add :cost_bps, :float
      add :net_bps, :float
      add :status, :string, null: false, default: "open"
      add :confidence, :float
      add :threshold, :float
      add :regime, :float

      timestamps()
    end

    create index(:paper_trades, [:arm, :status])
    create index(:paper_trades, [:entry_ts])
    create index(:paper_trades, [:exit_ts])
    # Invariant 2 of the policy: one open position per pair per arm, always.
    create unique_index(:paper_trades, [:arm, :pair],
             where: "status = 'open'",
             name: :paper_trades_one_open_per_pair
           )
  end
end
