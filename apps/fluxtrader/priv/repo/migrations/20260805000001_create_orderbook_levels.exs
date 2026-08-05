defmodule FluxTrader.Repo.Migrations.CreateOrderbookLevels do
  use Ecto.Migration

  @moduledoc """
  Raw L2 order-book ladder, stored losslessly alongside the compressed
  `orderbook_snapshots` scalar features. Motivation: L2 depth has NO historical
  backfill (see docs/DATA_COLLECTION_AUDIT.md) — the previous collector fetched 20
  levels and discarded the raw ladder, keeping only 11 aggregate floats, so that
  detail was unrecoverable. This table preserves the full ladder per snapshot.

  One row per snapshot (bids/asks as JSONB arrays of [price, qty]) rather than one
  row per level, to avoid ~200x row inflation. Joins to `orderbook_snapshots` on
  (symbol, ts).
  """

  def change do
    create table(:orderbook_levels, primary_key: false) do
      add :symbol, :string, null: false
      # Local collection time; MUST match the paired orderbook_snapshots.ts so the
      # two tables join 1:1 on (symbol, ts).
      add :ts, :utc_datetime_usec, null: false
      # Exchange-provided timestamps from the depth payload (E = event time,
      # T = transaction time) — kept so we can later correct for collection jitter.
      # Nullable: not every depth response carries them.
      add :event_time, :utc_datetime_usec
      add :transaction_time, :utc_datetime_usec
      # Binance depth `lastUpdateId` — lets us order/dedup snapshots and detect gaps.
      add :last_update_id, :bigint
      # Number of levels actually captured on each side (<= requested depth limit).
      add :depth, :integer, null: false, default: 0
      # Full ladders: JSONB arrays of [price, qty] pairs (numeric), best-first.
      # jsonb (not float[][]) so we keep exact values and tolerate ragged lengths.
      add :bids, :jsonb, null: false, default: fragment("'[]'::jsonb")
      add :asks, :jsonb, null: false, default: fragment("'[]'::jsonb")
    end

    create unique_index(:orderbook_levels, [:symbol, :ts])
    create index(:orderbook_levels, [:ts])
  end
end
