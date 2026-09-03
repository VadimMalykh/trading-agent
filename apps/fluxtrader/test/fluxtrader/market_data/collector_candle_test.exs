defmodule FluxTrader.MarketData.CollectorCandleTest do
  @moduledoc """
  Regression test for the candle-poll defect (docs/CANDLE_POLL_DEFECT.md).

  `/fapi/v1/klines` returns the still-forming bar as its newest row, so the poller sees
  every bar for the first time roughly a minute after it opens and then re-sees it, closed,
  on later polls. While the write used `on_conflict: :nothing` that first partial snapshot
  was frozen forever: from 2026-07-18 to 2026-09-03 every stored 5m candle carried ~10% of
  the true volume and ~30% of the true high-low range. The write must therefore REPLACE.
  """
  use FluxTrader.DataCase, async: true

  alias FluxTrader.Data.Candle
  alias FluxTrader.MarketData.Collector

  @open_time ~U[2026-09-03 12:00:00.000000Z]

  defp candle(attrs) do
    Map.merge(
      %{
        symbol: "BTCUSDT",
        interval: "5m",
        open_time: @open_time,
        open: 100.0,
        high: 100.5,
        low: 99.9,
        close: 100.2,
        volume: 12.0,
        close_time: ~U[2026-09-03 12:04:59.999000Z]
      },
      attrs
    )
  end

  defp stored do
    Repo.one!(from c in Candle, where: c.symbol == "BTCUSDT" and c.open_time == ^@open_time)
  end

  test "a closed bar overwrites the partial snapshot stored for the same open_time" do
    # First poll: the bar has been open ~60s, so only its first minute is in the kline.
    assert {:ok, _} = Collector.store_candle(candle(%{}))

    # A later poll returns the same open_time, now closed: more volume, wider range, and
    # the real close. Before the fix this row was silently dropped.
    assert {:ok, _} =
             Collector.store_candle(
               candle(%{high: 103.0, low: 98.0, close: 102.5, volume: 118.0})
             )

    row = stored()
    assert row.volume == 118.0
    assert row.high == 103.0
    assert row.low == 98.0
    assert row.close == 102.5
    # Still one row per (symbol, interval, open_time) — the replace must not duplicate.
    assert Repo.aggregate(from(c in Candle, where: c.symbol == "BTCUSDT"), :count) == 1
  end

  test "candles of different intervals at the same open_time do not overwrite each other" do
    assert {:ok, _} = Collector.store_candle(candle(%{interval: "5m", volume: 118.0}))
    assert {:ok, _} = Collector.store_candle(candle(%{interval: "1m", volume: 9.0}))

    assert Repo.aggregate(from(c in Candle, where: c.symbol == "BTCUSDT"), :count) == 2
    assert Repo.one!(from c in Candle, where: c.interval == "5m", select: c.volume) == 118.0
    assert Repo.one!(from c in Candle, where: c.interval == "1m", select: c.volume) == 9.0
  end
end
