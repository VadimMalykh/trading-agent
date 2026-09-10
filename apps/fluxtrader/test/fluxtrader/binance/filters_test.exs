defmodule FluxTrader.Binance.FiltersTest do
  use ExUnit.Case, async: true

  alias FluxTrader.Binance.Filters

  @info %{
    "symbols" => [
      %{
        "symbol" => "BTCUSDT",
        "quantityPrecision" => 3,
        "pricePrecision" => 1,
        "filters" => [
          %{"filterType" => "LOT_SIZE", "stepSize" => "0.001"},
          %{"filterType" => "PRICE_FILTER", "tickSize" => "0.10"},
          %{"filterType" => "MIN_NOTIONAL", "notional" => "100"}
        ]
      }
    ]
  }

  setup do
    {:ok, f: Filters.from_exchange_info(@info)["BTCUSDT"]}
  end

  test "parses the three filters that matter", %{f: f} do
    assert f.step == 0.001
    assert f.tick == 0.1
    assert f.min_notional == 100.0
  end

  test "quantity rounds DOWN to the lot step — never up", %{f: f} do
    # RiskManager's 1000 * 0.10 / 100_000 * 5 = 0.005; a 5/3-size trade is 0.008333...
    assert Filters.round_qty(f, 0.0083333) == 0.008
    assert Filters.round_qty(f, 0.0089999) == 0.008
    assert Filters.round_qty(f, 0.009) == 0.009
  end

  test "prices round to the tick", %{f: f} do
    assert Filters.round_price(f, 98_000.04) == 98_000.0
    assert Filters.round_price(f, 98_000.06) == 98_000.1
  end

  test "an order below the minimum notional is refused before it is sent", %{f: f} do
    # One lot at $90k is $90: under the $100 floor. Less than one lot is no order at all.
    assert {:error, :below_min_notional} = Filters.sized_qty(f, 0.0015, 90_000.0)
    assert {:error, :zero_quantity} = Filters.sized_qty(f, 0.0009, 100_000.0)
    assert {:ok, 0.008} = Filters.sized_qty(f, 0.0083, 100_000.0)
  end
end
