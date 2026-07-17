defmodule FluxTrader.MarketData.MarketTrade do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key false
  schema "market_trades" do
    field :symbol, :string
    field :window_start, :utc_datetime_usec
    field :trade_count, :integer
    field :volume, :float
    field :buy_volume, :float
    field :sell_volume, :float
    field :vwap, :float
    field :high, :float
    field :low, :float
  end

  def changeset(row, attrs) do
    row
    |> cast(attrs, [
      :symbol,
      :window_start,
      :trade_count,
      :volume,
      :buy_volume,
      :sell_volume,
      :vwap,
      :high,
      :low
    ])
    |> validate_required([:symbol, :window_start, :trade_count, :volume, :buy_volume, :sell_volume])
  end
end
