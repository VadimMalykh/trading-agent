defmodule FluxTrader.MarketData.BookFeaturesTest do
  @moduledoc """
  BOOK_WAVE2_PLAN §L1 / option 2: the archive-style band sums, the reach numbers, the
  unchanged top-20 scalars, and the 100-level truncation of the stored ladder.
  """
  use ExUnit.Case, async: true

  alias FluxTrader.MarketData.BookFeatures

  # 300 bids one bp apart from 100.0 downward, 300 asks one bp apart from 100.01 upward,
  # qty = level + 1 — the same made-up ladder m3/ladderspan.py's tests use.
  defp depth(n \\ 300) do
    bids = for i <- 0..(n - 1), do: [Float.to_string(100.0 * (1 - 0.0001 * i)), Float.to_string(i + 1.0)]
    asks = for i <- 0..(n - 1), do: [Float.to_string(100.01 * (1 + 0.0001 * i)), Float.to_string(i + 1.0)]
    %{"bids" => bids, "asks" => asks, "E" => 1_760_000_000_000, "T" => 1_760_000_000_001, "lastUpdateId" => 7}
  end

  test "band sums are mid-referenced sums over the whole fetched ladder" do
    {:ok, f} = BookFeatures.from_depth("XUSDT", depth())
    assert_in_delta f.mid, 100.005, 1.0e-9
    # ±0.2 %: edge 99.80499 -> bid levels 0..19 -> 1 + … + 20 = 210
    assert_in_delta f.bid_band_0_2, 210.0, 1.0e-9
    # ±1 %: edge 99.00495 -> levels 0..99 -> 5050
    assert_in_delta f.bid_band_1, 5050.0, 1.0e-9
    # ±2 %: edge 98.0049 -> levels 0..199 -> 20100
    assert_in_delta f.bid_band_2, 20_100.0, 1.0e-9
    # ±3 % and beyond: the whole 300-level ladder (45150) — and reach says it is NOT covered
    assert_in_delta f.bid_band_3, 45_150.0, 1.0e-9
    assert_in_delta f.bid_band_5, 45_150.0, 1.0e-9
    assert f.ask_band_0_2 > 0 and f.ask_band_1 > f.ask_band_0_2
    assert f.depth_fetched == 300
  end

  test "reach is the deepest level's distance from the mid in bps" do
    {:ok, f} = BookFeatures.from_depth("XUSDT", depth())
    deepest_bid = 100.0 * (1 - 0.0001 * 299)
    assert_in_delta f.bid_reach_bps, (100.005 - deepest_bid) / 100.005 * 10_000.0, 1.0e-9
    # covers ±2 % (200 bps) but not ±3 %
    assert f.bid_reach_bps >= 200.0 and f.bid_reach_bps < 300.0
    assert f.ask_reach_bps >= 200.0 and f.ask_reach_bps < 300.0
  end

  test "the scalars still read the top 20 levels only" do
    {:ok, deep} = BookFeatures.from_depth("XUSDT", depth(300))
    {:ok, shallow} = BookFeatures.from_depth("XUSDT", depth(20))
    for k <- [:mid, :spread, :microprice, :bid_volume, :ask_volume, :imbalance,
              :bid_depth_near, :ask_depth_near, :bid_depth_far, :ask_depth_far] do
      assert_in_delta Map.fetch!(deep, k), Map.fetch!(shallow, k), 1.0e-9
    end
    # the shallow ladder's bands are partial and its reach says so
    assert shallow.bid_reach_bps < 20.0
    assert shallow.bid_band_0_2 == shallow.bid_volume
  end

  test "the stored ladder is truncated to 100 levels, best-first, with depth = stored count" do
    {:ok, raw} = BookFeatures.raw_levels("XUSDT", depth(300), DateTime.utc_now())
    assert length(raw.bids) == BookFeatures.stored_levels()
    assert length(raw.asks) == 100
    assert raw.depth == 100
    assert hd(raw.bids) == [100.0, 1.0]
    assert List.last(raw.bids) == [100.0 * (1 - 0.0001 * 99), 100.0]
  end

  test "band keys match the schema's column names" do
    keys = for pct <- BookFeatures.band_pcts(), side <- [:bid, :ask], do: BookFeatures.band_key(side, pct)
    assert :bid_band_0_2 in keys and :ask_band_1 in keys and :bid_band_5 in keys
    schema = FluxTrader.MarketData.OrderbookSnapshot.band_fields()
    for k <- keys, do: assert k in schema
  end
end
