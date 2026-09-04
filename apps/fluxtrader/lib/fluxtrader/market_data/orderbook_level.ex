defmodule FluxTrader.MarketData.OrderbookLevel do
  @moduledoc """
  Raw L2 order-book ladder for a single snapshot, stored losslessly to complement
  the compressed scalar features in `FluxTrader.MarketData.OrderbookSnapshot`.

  `bids` / `asks` are arrays of `[price, qty]` pairs (best-first). Joins to
  `orderbook_snapshots` on `(symbol, ts)`. See docs/archive/DATA_COLLECTION_AUDIT.md for why
  the raw ladder is captured (no historical backfill exists for L2 depth).
  """
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "orderbook_levels" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    field :event_time, :utc_datetime_usec
    field :transaction_time, :utc_datetime_usec
    field :last_update_id, :integer
    field :depth, :integer, default: 0
    field :bids, {:array, {:array, :float}}, default: []
    field :asks, {:array, {:array, :float}}, default: []
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [
      :symbol,
      :ts,
      :event_time,
      :transaction_time,
      :last_update_id,
      :depth,
      :bids,
      :asks
    ])
    |> validate_required([:symbol, :ts, :bids, :asks])
  end
end
