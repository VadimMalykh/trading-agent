defmodule FluxTrader.Trading.ExecCostTest do
  use ExUnit.Case, async: true

  alias FluxTrader.Trading.ExecCost

  test "per-pair costs are the measured ones from M3_4_RESULTS.md §1" do
    assert {:measured, 8.017} = ExecCost.round_trip_bps("BTCUSDT")
    assert {:measured, 14.060} = ExecCost.round_trip_bps("WLDUSDT")
    assert {:measured, 8.017} = ExecCost.round_trip_bps("btcusdt")
  end

  test "an unmeasured pair falls back to the pooled cost and says so" do
    # Charging BTC's 8.0 bps on a pair whose spread was never measured would make a
    # backtest look better than the market.
    assert {:pooled_fallback, 9.842} = ExecCost.round_trip_bps("XRPUSDT")
  end

  test "the eight measured pairs are the eight served pairs (T6 closed 8-vs-12)" do
    assert ExecCost.measured_pairs() ==
             Enum.sort([
               "BTCUSDT",
               "ETHUSDT",
               "SOLUSDT",
               "DOGEUSDT",
               "WLDUSDT",
               "HYPEUSDT",
               "ZECUSDT",
               "1000PEPEUSDT"
             ])
  end

  test "every measured pair is cheaper than the 14 bps M3 used to assume" do
    # Q1's headline: the interval excludes 14 and every published M3 number was too
    # pessimistic. WLDUSDT is the one pair that reaches it.
    Enum.each(ExecCost.measured_pairs(), fn p ->
      assert ExecCost.cost_bps(p) <= 14.060
    end)

    assert ExecCost.pooled_bps() < 14.0
  end

  test "net_bps books gross minus cost x size, exactly as metrics.summarise does" do
    # 0.003 = 30 bps gross; BTC costs 8.017 round trip; size 5/3 crosses 5/3 the notional.
    assert_in_delta ExecCost.net_bps("BTCUSDT", 0.003, 1.0), 30.0 - 8.017, 1.0e-9
    assert_in_delta ExecCost.net_bps("BTCUSDT", 0.003, 5 / 3), 30.0 - 8.017 * 5 / 3, 1.0e-9
  end

  test "side cost is half the round trip" do
    assert_in_delta ExecCost.side_bps("BTCUSDT"), 8.017 / 2, 1.0e-9
  end
end
