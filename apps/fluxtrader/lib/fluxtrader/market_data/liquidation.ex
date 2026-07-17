defmodule FluxTrader.MarketData.Liquidation do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "liquidations" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    field :side, :string
    field :price, :float
    field :quantity, :float
    field :order_id, :string
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [:symbol, :ts, :side, :price, :quantity, :order_id])
    |> validate_required([:symbol, :ts])
  end
end
