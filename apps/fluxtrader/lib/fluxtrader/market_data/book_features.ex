defmodule FluxTrader.MarketData.BookFeatures do
  @moduledoc """
  Compress L2 top-N book into model-friendly features.
  """

  @doc """
  Parse Binance depth response into feature map.

  Expects %{"bids" => [[price, qty], ...], "asks" => [[price, qty], ...]}
  """
  def from_depth(symbol, depth) when is_map(depth) do
    bids = parse_levels(Map.get(depth, "bids", []))
    asks = parse_levels(Map.get(depth, "asks", []))

    if bids == [] or asks == [] do
      {:error, :empty_book}
    else
      best_bid = hd(bids)
      best_ask = hd(asks)
      mid = (best_bid.price + best_ask.price) / 2.0
      spread = best_ask.price - best_bid.price

      bid_vol = Enum.reduce(bids, 0.0, fn l, acc -> acc + l.qty end)
      ask_vol = Enum.reduce(asks, 0.0, fn l, acc -> acc + l.qty end)
      total = bid_vol + ask_vol
      imbalance = if total > 0, do: (bid_vol - ask_vol) / total, else: 0.0

      near_n = min(5, min(length(bids), length(asks)))
      bid_near = bids |> Enum.take(near_n) |> Enum.reduce(0.0, fn l, a -> a + l.qty end)
      ask_near = asks |> Enum.take(near_n) |> Enum.reduce(0.0, fn l, a -> a + l.qty end)
      bid_far = bid_vol - bid_near
      ask_far = ask_vol - ask_near

      microprice =
        if best_bid.qty + best_ask.qty > 0 do
          (best_ask.price * best_bid.qty + best_bid.price * best_ask.qty) /
            (best_bid.qty + best_ask.qty)
        else
          mid
        end

      {:ok,
       %{
         symbol: symbol,
         ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
         mid: mid,
         spread: spread,
         microprice: microprice,
         bid_volume: bid_vol,
         ask_volume: ask_vol,
         imbalance: imbalance,
         bid_depth_near: bid_near,
         ask_depth_near: ask_near,
         bid_depth_far: bid_far,
         ask_depth_far: ask_far
       }}
    end
  end

  def from_depth(_, _), do: {:error, :invalid_depth}

  defp parse_levels(levels) do
    Enum.map(levels, fn
      [price, qty | _] when is_binary(price) and is_binary(qty) ->
        %{price: to_f(price), qty: to_f(qty)}

      [price, qty | _] ->
        %{price: to_f(price), qty: to_f(qty)}

      _ ->
        nil
    end)
    |> Enum.reject(&is_nil/1)
  end

  defp to_f(v) when is_binary(v), do: String.to_float(v)
  defp to_f(v) when is_float(v), do: v
  defp to_f(v) when is_integer(v), do: v * 1.0
end
