defmodule FluxTrader.Repo.Migrations.AddExchangeEventTimes do
  use Ecto.Migration

  @moduledoc """
  B4.1 (docs/BOOK_ERA_PLAN.md §2) — store the EXCHANGE's own timestamps alongside
  the collector's local wall clock.

  `orderbook_snapshots.ts`, `funding_rates.ts` and `open_interest.ts` are all
  `DateTime.utc_now()` at insert time, i.e. local receipt time. That includes the
  REST round trip and any scheduling jitter. At a 240m horizon this is noise; at a
  1m horizon it is a large fraction of the prediction window, so every short-horizon
  dataset built from these tables inherits an unknown, unrecoverable time skew.

  `orderbook_levels` already stores `event_time` / `transaction_time` (migration
  20260805000001); this mirrors that onto the scalar tables the model actually reads.

  Deliberately ADDITIVE and nullable:
    * `ts` keeps its exact current meaning, so every existing query, the training
      as-of joins (`ml/train/data/features.py`) and the 1:1 `(symbol, ts)` join to
      `orderbook_levels` are untouched.
    * Rows collected before this migration keep NULL, which is honest — the
      exchange time for those rows is genuinely unknown and must not be imputed.
  """

  def change do
    # Binance /fapi/v1/depth returns E (event time), T (transaction time) and
    # lastUpdateId. last_update_id also lets a consumer dedup/order snapshots and
    # detect gaps without joining orderbook_levels.
    alter table(:orderbook_snapshots) do
      add :event_time, :utc_datetime_usec
      add :transaction_time, :utc_datetime_usec
      add :last_update_id, :bigint
    end

    # /fapi/v1/premiumIndex and /fapi/v1/openInterest both return "time".
    alter table(:funding_rates) do
      add :event_time, :utc_datetime_usec
    end

    alter table(:open_interest) do
      add :event_time, :utc_datetime_usec
    end
  end
end
