defmodule FluxTrader.Repo.Migrations.CreateLongShortRatios do
  use Ecto.Migration

  @moduledoc """
  B4.2 (docs/BOOK_ERA_PLAN.md §2) — positioning / sentiment ratios, which we are
  not collecting at all today.

  Binance keeps `/futures/data/*Ratio` for only ~30 days, so this is
  collector-only history beyond that window: every day we do not poll is a day
  permanently missing. That is the whole reason B4 is "start now" and independent
  of B0–B3.

  Three endpoints, one row: they share `(symbol, timestamp, period)` so folding
  them into a single wide row keeps the downstream join trivial (one as-of join
  instead of three). Each poll upserts only its own columns
  (`on_conflict: {:replace, ...}` in the collector), so a failure of one endpoint
  never blanks another's data.

    * topLongShortAccountRatio     -> top_* (top traders by margin balance)
    * globalLongShortAccountRatio  -> global_* (all accounts)
    * takerlongshortRatio          -> taker_* (aggressor buy/sell volume)

  `period` is stored explicitly because the exchange's minimum granularity is 5m
  and we may later add a coarser series; it is part of the uniqueness key so the
  two would coexist rather than collide.
  """

  def change do
    create table(:long_short_ratios, primary_key: false) do
      add :symbol, :string, null: false
      # EXCHANGE bucket timestamp (the endpoints' "timestamp" field), NOT local
      # collection time — unlike the older market-data tables this one has no
      # jitter to correct for.
      add :ts, :utc_datetime_usec, null: false
      add :period, :string, null: false, default: "5m"

      add :top_long_short_ratio, :float
      add :top_long_account, :float
      add :top_short_account, :float

      add :global_long_short_ratio, :float
      add :global_long_account, :float
      add :global_short_account, :float

      add :taker_buy_sell_ratio, :float
      add :taker_buy_vol, :float
      add :taker_sell_vol, :float
    end

    create unique_index(:long_short_ratios, [:symbol, :ts, :period])
    create index(:long_short_ratios, [:ts])
  end
end
