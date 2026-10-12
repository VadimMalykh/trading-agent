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

  # The archive-style depth bands (docs/BOOK_WAVE2_PLAN.md §L1, Vadim's option 2, 2026-10-12):
  # quantity resting within x % of the MID on each side, for the same x Binance's public
  # bookDepth archive publishes (±0.2, ±1, ±2, ±3, ±4, ±5 %). L1 measured the archive's number
  # to be exactly this sum (median ratio 1.000 on every reachable pair-band), so a feature
  # trained on the archive's history can be served from these columns. Computed over the WHOLE
  # fetched ladder (the deep poll), never the scalar top-20.
  @band_pcts [0.2, 1.0, 2.0, 3.0, 4.0, 5.0]

  # The raw ladder stored in `orderbook_levels` stays at 100 levels whatever the poll fetches:
  # the deeper poll exists for the band sums above, and a 500-level ladder would grow the disk
  # at ~5x (BACKLOG "Disk budget"). The band sums are what the ladder was for.
  @stored_levels 100

  def band_pcts, do: @band_pcts
  def stored_levels, do: @stored_levels

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
    all_bids = depth |> Map.get("bids", []) |> parse_levels()
    all_asks = depth |> Map.get("asks", []) |> parse_levels()
    bids = Enum.take(all_bids, @scalar_levels)
    asks = Enum.take(all_asks, @scalar_levels)

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
       }
       |> Map.merge(bands(all_bids, all_asks, mid))}
    end
  end

  def from_depth(_, _), do: {:error, :invalid_depth}

  @doc """
  The archive-style band sums over the whole fetched ladder, plus the two numbers that say
  whether the ladder REACHES a band: the distance of the deepest level from the mid on each
  side, in bps. A band is covered iff that distance is at least the band's width — a reader
  must mask a band the ladder did not reach rather than take its partial sum as the depth.

  Keys: `bid_band_0_2`, `ask_band_0_2`, `bid_band_1` … `ask_band_5`, `bid_reach_bps`,
  `ask_reach_bps`, `depth_fetched`. Bids are `price >= mid * (1 - x)`, asks `price <= mid * (1 + x)`.
  """
  def bands(bids, asks, mid) when is_list(bids) and is_list(asks) and is_number(mid) do
    base =
      Enum.reduce(@band_pcts, %{}, fn pct, acc ->
        x = pct / 100.0
        lo = mid * (1.0 - x)
        hi = mid * (1.0 + x)
        b = bids |> Enum.filter(&(&1.price >= lo)) |> Enum.reduce(0.0, fn l, a -> a + l.qty end)
        k = asks |> Enum.filter(&(&1.price <= hi)) |> Enum.reduce(0.0, fn l, a -> a + l.qty end)

        acc
        |> Map.put(band_key(:bid, pct), b)
        |> Map.put(band_key(:ask, pct), k)
      end)

    deepest_bid = bids |> Enum.map(& &1.price) |> Enum.min(fn -> mid end)
    deepest_ask = asks |> Enum.map(& &1.price) |> Enum.max(fn -> mid end)

    Map.merge(base, %{
      bid_reach_bps: (mid - deepest_bid) / mid * 10_000.0,
      ask_reach_bps: (deepest_ask - mid) / mid * 10_000.0,
      depth_fetched: max(length(bids), length(asks))
    })
  end

  @doc "`:bid_band_0_2`, `:ask_band_1`, … — the column name for a side and a band percent."
  def band_key(side, pct) do
    tag =
      pct
      |> :erlang.float_to_binary(decimals: 1)
      |> String.replace(~r/\.0$/, "")
      |> String.replace(".", "_")

    String.to_atom("#{side}_band_#{tag}")
  end

  @doc """
  Extract the FULL raw ladder + exchange metadata from a Binance depth response,
  shaped for `FluxTrader.MarketData.OrderbookLevel`. `ts` is passed in so the raw
  row shares the exact timestamp of its paired `orderbook_snapshots` row (1:1 join
  on symbol+ts). Returns `{:ok, attrs}` or `{:error, reason}`.

  Levels are `[price, qty]` numeric pairs, best-first. Since 2026-10-12 the stored ladder is
  truncated to `stored_levels/0` (100) — the poll goes deeper for the band sums in
  `bands/3`, and `depth` records how many levels THIS ROW holds, not how many were fetched
  (that is `orderbook_snapshots.depth_fetched`).
  """
  def raw_levels(symbol, depth, ts) when is_map(depth) do
    bids = depth |> Map.get("bids", []) |> parse_pairs() |> Enum.take(@stored_levels)
    asks = depth |> Map.get("asks", []) |> parse_pairs() |> Enum.take(@stored_levels)

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
