defmodule FluxTrader.MarketData.OrderbookSnapshot do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "orderbook_snapshots" do
    field :symbol, :string
    # Local collection time. Keeps its historical meaning — training's as-of joins
    # and the 1:1 join to orderbook_levels are both on (symbol, ts).
    field :ts, :utc_datetime_usec
    # Exchange-provided times from the depth payload (E / T) and lastUpdateId.
    # NULL for rows collected before migration 20260824000001. See B4.1.
    field :event_time, :utc_datetime_usec
    field :transaction_time, :utc_datetime_usec
    field :last_update_id, :integer
    field :mid, :float
    field :spread, :float
    field :microprice, :float
    field :bid_volume, :float
    field :ask_volume, :float
    field :imbalance, :float
    field :bid_depth_near, :float
    field :ask_depth_near, :float
    field :bid_depth_far, :float
    field :ask_depth_far, :float
    # Archive-style depth bands over the whole fetched ladder (migration 20261012000001,
    # BOOK_WAVE2_PLAN §L1): quantity within x % of the mid per side, the deepest level's
    # distance from the mid (bps) per side — a band is valid only where reach >= its width —
    # and how many levels the poll returned. NULL on rows collected before the migration.
    field :bid_band_0_2, :float
    field :ask_band_0_2, :float
    field :bid_band_1, :float
    field :ask_band_1, :float
    field :bid_band_2, :float
    field :ask_band_2, :float
    field :bid_band_3, :float
    field :ask_band_3, :float
    field :bid_band_4, :float
    field :ask_band_4, :float
    field :bid_band_5, :float
    field :ask_band_5, :float
    field :bid_reach_bps, :float
    field :ask_reach_bps, :float
    field :depth_fetched, :integer
  end

  @band_fields [
    :bid_band_0_2, :ask_band_0_2, :bid_band_1, :ask_band_1, :bid_band_2, :ask_band_2,
    :bid_band_3, :ask_band_3, :bid_band_4, :ask_band_4, :bid_band_5, :ask_band_5,
    :bid_reach_bps, :ask_reach_bps, :depth_fetched
  ]
  def band_fields, do: @band_fields

  def changeset(row, attrs) do
    row
    |> cast(attrs, [
      :symbol,
      :ts,
      :event_time,
      :transaction_time,
      :last_update_id,
      :mid,
      :spread,
      :microprice,
      :bid_volume,
      :ask_volume,
      :imbalance,
      :bid_depth_near,
      :ask_depth_near,
      :bid_depth_far,
      :ask_depth_far
      | @band_fields
    ])
    |> validate_required([:symbol, :ts, :mid, :spread, :bid_volume, :ask_volume, :imbalance])
  end
end
