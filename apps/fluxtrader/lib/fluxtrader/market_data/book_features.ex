defmodule FluxTrader.MarketData.BookFeatures do
  @moduledoc """
  Compress L2 top-N book into model-friendly features.

  The collector now fetches a DEEP book (see BOOK_DEPTH_LIMIT) and stores the raw
  ladder separately (`OrderbookLevel`). To keep the served model's feature
  distribution stable, the 11 scalar features here are computed over only the top
  `@scalar_levels` levels — the same depth the model was trained on — regardless of
  how many levels were fetched. See docs/archive/DATA_COLLECTION_AUDIT.md.
  """

  # Number of book levels used to compute the compressed scalar features. Fixed at
  # 20 to preserve the semantics the served model was trained on even though the
  # collector may now pull far more levels for the raw ladder.
  @scalar_levels 20

  @doc """
  Parse Binance depth response into feature map.

  Expects %{"bids" => [[price, qty], ...], "asks" => [[price, qty], ...]}

  Only the top #{@scalar_levels} levels per side feed the scalar features (stable
  semantics); the raw ladder is captured separately via `raw_levels/1`.

  The returned map also carries the exchange's `E` / `T` / `lastUpdateId` so
  `orderbook_snapshots` records the exchange clock next to the local one (B4.1).
  These are additions — no existing scalar changes value.
  """
  def from_depth(symbol, depth) when is_map(depth) do
    bids = depth |> Map.get("bids", []) |> parse_levels() |> Enum.take(@scalar_levels)
    asks = depth |> Map.get("asks", []) |> parse_levels() |> Enum.take(@scalar_levels)

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
         # Local receipt time — the key everything else joins on. The exchange's
         # own clock is carried alongside it (B4.1) so a short-horizon consumer can
         # correct for REST round-trip jitter instead of guessing at it.
         ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
         event_time: ms_to_dt(Map.get(depth, "E")),
         transaction_time: ms_to_dt(Map.get(depth, "T")),
         last_update_id: as_int(Map.get(depth, "lastUpdateId")),
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

  @doc """
  Extract the FULL raw ladder + exchange metadata from a Binance depth response,
  shaped for `FluxTrader.MarketData.OrderbookLevel`. `ts` is passed in so the raw
  row shares the exact timestamp of its paired `orderbook_snapshots` row (1:1 join
  on symbol+ts). Returns `{:ok, attrs}` or `{:error, reason}`.

  Levels are `[price, qty]` numeric pairs, best-first, with NO top-N truncation —
  this is the lossless capture the scalar features intentionally discard.
  """
  def raw_levels(symbol, depth, ts) when is_map(depth) do
    bids = depth |> Map.get("bids", []) |> parse_pairs()
    asks = depth |> Map.get("asks", []) |> parse_pairs()

    if bids == [] or asks == [] do
      {:error, :empty_book}
    else
      {:ok,
       %{
         symbol: symbol,
         ts: ts,
         event_time: ms_to_dt(Map.get(depth, "E")),
         transaction_time: ms_to_dt(Map.get(depth, "T")),
         last_update_id: as_int(Map.get(depth, "lastUpdateId")),
         depth: max(length(bids), length(asks)),
         bids: bids,
         asks: asks
       }}
    end
  end

  def raw_levels(_, _, _), do: {:error, :invalid_depth}

  # Parse raw depth into a list of [price, qty] float pairs (for JSONB storage).
  defp parse_pairs(levels) do
    Enum.reduce(levels, [], fn
      [price, qty | _], acc -> [[to_f(price), to_f(qty)] | acc]
      _, acc -> acc
    end)
    |> Enum.reverse()
  end

  defp ms_to_dt(nil), do: nil

  defp ms_to_dt(ms) when is_integer(ms),
    do: DateTime.from_unix!(ms, :millisecond) |> DateTime.truncate(:microsecond)

  defp ms_to_dt(_), do: nil

  defp as_int(v) when is_integer(v), do: v

  defp as_int(v) when is_binary(v) do
    case Integer.parse(v) do
      {int, _} -> int
      :error -> nil
    end
  end

  defp as_int(_), do: nil

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

  defp to_f(nil), do: 0.0
  defp to_f(v) when is_float(v), do: v
  defp to_f(v) when is_integer(v), do: v * 1.0

  defp to_f(v) when is_binary(v) do
    case Float.parse(v) do
      {f, _} -> f
      :error -> 0.0
    end
  end

  defp to_f(_), do: 0.0
end
