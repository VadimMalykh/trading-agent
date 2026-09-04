defmodule FluxTrader.MarketData.LongShortRatio do
  @moduledoc """
  Positioning / sentiment ratios from Binance's `/futures/data/*Ratio` endpoints,
  folded into one row per `(symbol, ts, period)`.

  `ts` is the EXCHANGE bucket timestamp, not local collection time. The exchange
  retains these series for only ~30 days, so anything older than that exists only
  because we stored it — see docs/archive/DATA_COLLECTION_AUDIT.md and
  docs/BOOK_ERA_PLAN.md B4.

  The three endpoints are polled independently and each upserts only its own
  column group, so a nil group means "that endpoint has not answered for this
  bucket yet", not "the value is zero".
  """
  use Ecto.Schema
  import Ecto.Changeset

  @fields [
    :symbol,
    :ts,
    :period,
    :top_long_short_ratio,
    :top_long_account,
    :top_short_account,
    :global_long_short_ratio,
    :global_long_account,
    :global_short_account,
    :taker_buy_sell_ratio,
    :taker_buy_vol,
    :taker_sell_vol
  ]

  @primary_key false
  schema "long_short_ratios" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    field :period, :string, default: "5m"

    # Top traders by margin balance.
    field :top_long_short_ratio, :float
    field :top_long_account, :float
    field :top_short_account, :float

    # All accounts.
    field :global_long_short_ratio, :float
    field :global_long_account, :float
    field :global_short_account, :float

    # Aggressor (taker) volume split.
    field :taker_buy_sell_ratio, :float
    field :taker_buy_vol, :float
    field :taker_sell_vol, :float
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, @fields)
    |> validate_required([:symbol, :ts, :period])
  end
end
