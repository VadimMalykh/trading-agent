defmodule FluxTrader.Data.FeatureEngineering do
  @moduledoc """
  Computes technical indicators and ML features from raw candle data.
  """

  def compute_features(candles) when length(candles) < 20, do: %{}

  def compute_features(candles) do
    closes = Enum.map(candles, & &1.close)
    volumes = Enum.map(candles, & &1.volume)
    highs = Enum.map(candles, & &1.high)
    lows = Enum.map(candles, & &1.low)

    %{
      sma_10: sma(closes, 10),
      sma_20: sma(closes, 20),
      ema_12: ema(closes, 12),
      ema_26: ema(closes, 26),
      rsi_14: rsi(closes, 14),
      macd: macd(closes),
      atr_14: atr(highs, lows, closes, 14),
      volume_sma: sma(volumes, 20),
      bollinger: bollinger_bands(closes, 20),
      current_price: List.last(closes),
      price_change_1h: price_change(closes, 1),
      price_change_4h: price_change(closes, 4),
      volume_ratio: volume_ratio(volumes)
    }
  end

  defp sma(data, period) when length(data) >= period do
    data
    |> Enum.take(-period)
    |> Enum.sum()
    |> Kernel./(period)
  end

  defp sma(_, _), do: 0.0

  defp ema(data, period) do
    k = 2 / (period + 1)

    data
    |> Enum.take(-period * 2)
    |> Enum.reduce({nil, fn val, prev -> val * k + prev * (1 - k) end}, fn
      val, {nil, _acc} -> {val, val}
      val, {prev, acc} -> {prev, acc.(val, prev)}
    end)
    |> elem(1)
  end

  defp rsi(closes, period) do
    {gains, losses} =
      closes
      |> Enum.take(-period - 1)
      |> Enum.chunk_every(2, 1, :discard)
      |> Enum.reduce({[], []}, fn [a, b], {gains, losses} ->
        diff = b - a
        if diff > 0, do: {[diff | gains], losses}, else: {gains, [-diff | losses]}
      end)

    avg_gain = if gains == [], do: 0, else: Enum.sum(gains) / period
    avg_loss = if losses == [], do: 0, else: Enum.sum(losses) / period

    if avg_loss == 0, do: 100.0, else: 100 - 100 / (1 + avg_gain / avg_loss)
  end

  defp macd(closes) do
    ema_12 = ema(closes, 12)
    ema_26 = ema(closes, 26)
    ema_12 - ema_26
  end

  defp atr(highs, lows, closes, period) do
    trs =
      Enum.zip([highs, lows, tl(closes)])
      |> Enum.map(fn {h, l, prev_c} ->
        max(h - l, max(abs(h - prev_c), abs(l - prev_c)))
      end)

    trs |> Enum.take(-period) |> Enum.sum() |> Kernel./(period)
  end

  defp bollinger_bands(closes, period) do
    recent = Enum.take(closes, -period)
    avg = Enum.sum(recent) / period
    variance = recent |> Enum.map(&((&1 - avg) |> :math.pow(2))) |> Enum.sum() |> Kernel./(period)
    std = :math.sqrt(variance)

    %{
      upper: avg + 2 * std,
      middle: avg,
      lower: avg - 2 * std
    }
  end

  defp price_change(closes, periods) do
    if length(closes) > periods do
      current = List.last(closes)
      prev = Enum.at(closes, -(periods + 1))
      (current - prev) / prev * 100
    else
      0.0
    end
  end

  defp volume_ratio(volumes) do
    recent = Enum.take(volumes, -20)

    if length(recent) >= 20 do
      current_vol = List.last(recent)
      avg_vol = Enum.sum(recent) / 20
      if avg_vol > 0, do: current_vol / avg_vol, else: 1.0
    else
      1.0
    end
  end
end
