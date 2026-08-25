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
  end

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
    ])
    |> validate_required([:symbol, :ts, :mid, :spread, :bid_volume, :ask_volume, :imbalance])
  end
end
