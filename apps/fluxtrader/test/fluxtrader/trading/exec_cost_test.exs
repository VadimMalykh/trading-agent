defmodule FluxTrader.Trading.ExecCostTest do
  use ExUnit.Case, async: true

  alias FluxTrader.Trading.ExecCost

  test "per-pair costs are the measured ones from M3_4_RESULTS.md §1" do
    assert {:measured, 8.017} = ExecCost.round_trip_bps("BTCUSDT")
    assert {:measured, 14.060} = ExecCost.round_trip_bps("WLDUSDT")
    assert {:measured, 8.017} = ExecCost.round_trip_bps("btcusdt")
  end

  test "the four short-window pairs carry their own cost, tagged by evidence depth" do
    # From the same M3-4 run's "four short-window pairs" table: 14 days of ladder rather
    # than 23, so they are charged normally but tagged so the depth stays visible.
    assert {:measured_short_window, 9.075} = ExecCost.round_trip_bps("XRPUSDT")
    assert {:measured_short_window, 10.754} = ExecCost.round_trip_bps("LINKUSDT")
    assert {:measured_short_window, 11.401} = ExecCost.round_trip_bps("AVAXUSDT")
    assert {:measured_short_window, 13.733} = ExecCost.round_trip_bps("ADAUSDT")
  end

  test "ADAUSDT is why the pooled fallback was not good enough to serve on" do
    # The concrete case for measuring before widening the universe: serving ADA on the
    # pooled number would have understated its round trip by 3.89 bps, about 40%.
    assert ExecCost.cost_bps("ADAUSDT") - ExecCost.pooled_bps() > 3.5
  end

  test "an unmeasured pair falls back to the pooled cost and says so" do
    # Charging BTC's 8.0 bps on a pair whose spread was never measured would make a
    # backtest look better than the market.
    assert {:pooled_fallback, 9.842} = ExecCost.round_trip_bps("BNBUSDT")
  end

  test "all twelve served pairs are measured, split 8 long-window / 4 short" do
    assert ExecCost.measured_pairs() ==
             Enum.sort([
               "BTCUSDT",
               "ETHUSDT",
               "SOLUSDT",
               "DOGEUSDT",
               "WLDUSDT",
               "HYPEUSDT",
               "ZECUSDT",
               "1000PEPEUSDT",
               "XRPUSDT",
               "LINKUSDT",
               "AVAXUSDT",
               "ADAUSDT"
             ])

    assert length(ExecCost.long_window_pairs()) == 8
    assert ExecCost.short_window_pairs() == Enum.sort(["XRPUSDT", "LINKUSDT", "AVAXUSDT", "ADAUSDT"])

    # The two lists partition the measured set — no pair is in both or neither.
    assert Enum.sort(ExecCost.long_window_pairs() ++ ExecCost.short_window_pairs()) ==
             ExecCost.measured_pairs()
  end

  test "the pooled number stays pooled over the eight long-window pairs only" do
    # M3_4_PROTOCOL §1.5: Q1 is a pre-registered decision quantity measured on 23 days, and
    # re-pooling it across two depths of evidence is exactly what the protocol forbids.
    assert ExecCost.pooled_bps() == 9.842
  end

  test "every long-window pair is cheaper than the 14 bps M3 used to assume" do
    # Q1's headline: the interval excludes 14 and every published M3 number was too
    # pessimistic. WLDUSDT is the one pair that reaches it. The short-window four are NOT
    # part of that claim — they never contributed to Q1's verdict.
    Enum.each(ExecCost.long_window_pairs(), fn p ->
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
