defmodule FluxTrader.MarketData.FundingRate do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "funding_rates" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    field :mark_price, :float
    field :index_price, :float
    field :last_funding_rate, :float
    field :next_funding_time, :utc_datetime_usec
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [:symbol, :ts, :mark_price, :index_price, :last_funding_rate, :next_funding_time])
    |> validate_required([:symbol, :ts])
  end
end
