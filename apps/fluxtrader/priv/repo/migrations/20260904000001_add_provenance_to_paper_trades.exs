defmodule FluxTrader.Repo.Migrations.AddProvenanceToPaperTrades do
  @moduledoc """
  Every forward trade records WHICH RULE took it (M3_PROTOCOL §9.6, decided 2026-09-04).

  Until now a checkpoint swap meant `TRUNCATE paper_trades`, because `Ledger.arm_summary/2`
  aggregates every closed row forever and two rules would blend. At ~2 trades a day and a
  quarterly retrain cadence that guarantees the forward ledger never accumulates. Tagging
  each row with the checkpoint and the constants in force makes the ledger a walk-forward
  record instead: the recipe is scored pooled across checkpoints, and any one checkpoint's
  rows can still be pulled out on their own.

  `threshold` (the cut in force) already exists on the row. This adds the two that were
  missing: the checkpoint identity and the ladder's top edge.
  """
  use Ecto.Migration

  def change do
    alter table(:paper_trades) do
      # sha256 of the served weights, as `ml_inference` reports it on /health. The policy
      # refuses to trade unless it equals `Policy.frozen_checkpoint_sha256/0`, so a row can
      # only ever carry the checkpoint its constants belong to.
      add :checkpoint, :string
      # `Policy.frozen_regime_edges/0`'s p80 at entry — enough to identify the ladder.
      add :ladder_p80, :float
    end

    create index(:paper_trades, [:checkpoint])
  end
end
