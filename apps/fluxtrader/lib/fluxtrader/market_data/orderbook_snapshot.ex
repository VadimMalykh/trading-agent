defmodule FluxTrader.MarketData.OrderbookSnapshot do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "orderbook_snapshots" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
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
