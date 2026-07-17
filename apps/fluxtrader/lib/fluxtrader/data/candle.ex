defmodule FluxTrader.Data.Candle do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "candles" do
    field :symbol, :string
    field :interval, :string
    field :open_time, :utc_datetime_usec
    field :open, :float
    field :high, :float
    field :low, :float
    field :close, :float
    field :volume, :float
    field :close_time, :utc_datetime_usec
  end

  @required_fields ~w(symbol interval open_time open high low close volume close_time)a

  def changeset(candle, attrs) do
    candle
    |> cast(attrs, @required_fields)
    |> validate_required(@required_fields)
    |> unique_constraint([:symbol, :interval, :open_time])
  end
end
