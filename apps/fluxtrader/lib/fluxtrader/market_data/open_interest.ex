defmodule FluxTrader.MarketData.OpenInterest do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "open_interest" do
    field :symbol, :string
    field :ts, :utc_datetime_usec
    field :open_interest, :float
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [:symbol, :ts, :open_interest])
    |> validate_required([:symbol, :ts, :open_interest])
  end
end
