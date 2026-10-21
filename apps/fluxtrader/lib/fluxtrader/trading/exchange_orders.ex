defmodule FluxTrader.Trading.ExchangeOrders do
  @moduledoc """
  A real position's life on the exchange: size it, open it, brake it, close it, and never
  take the exchange's word for granted.

  This is the `auto` path's order logic, pulled out of `Executor` so that it can be run by
  `mix flux.testnet_smoke` against the testnet without the trading application, and by the
  tests against `Binance.Trade.Fake` without a network. `Executor` calls it and writes the
  ledger row from what it returns; nothing here touches the database.

  ## Opening

  1. round the quantity **down** to the symbol's lot step and refuse it below the minimum
     notional (`Binance.Filters`) — the risk manager's arithmetic is not an order;
  2. set the symbol's leverage to what the risk manager approved, every time (idempotent);
  3. `MARKET` order with `newOrderRespType=RESULT`, then **reconcile**: while the returned
     status is not terminal, poll `GET /order` up to #{10} times. A row is written from
     `avgPrice` / `executedQty`, never from the price the signal carried;
  4. attach the brake — a `STOP_MARKET` and a `TAKE_PROFIT_MARKET`, both `closePosition`,
     both triggered on **mark price** so a wick in the last trade cannot fire them. They go
     through the **Algo Order API** (`POST /fapi/v1/algoOrder`, `algoType=CONDITIONAL`): on
     2026-09-10 the demo exchange rejected them on the plain order endpoint with `-4120`.
     The ids stored on the row are therefore **algo ids**; a triggered brake creates a
     normal order whose id is the algo's `actualOrderId`, and that is what fills. Q2 of
     REAL_MONEY_TRACK (2026-09-10) kept the 2% / 4% brake as insurance; the paper arms still
     ignore it and the offline price-path measurement prices it at ~10.5 gross bps a trade.
     A brake that fails to place is logged and the position is kept: the timed close still
     bounds it, and closing it straight back would pay two fees for nothing.

  ## Closing

  Cancel every resting order and algo order on the symbol first (the brake), then `MARKET
  reduceOnly` for the quantity that was actually filled at entry. If the exchange answers
  `-2022 ReduceOnly Order is rejected` there is no position to close — a brake fired first —
  so the stop and the target algos are read back, and whichever has an `actualOrderId`
  whose order is `FILLED` supplies the exit price and the reason.
  If neither did, the position is gone for a reason we did not cause (a liquidation, a
  manual close), and that is returned as `{:error, :position_missing}` for the caller to
  book loudly rather than guess at.

  ## The maker path (M2, BOOK_WAVE2_PLAN §M2, built 2026-10-21) — the pilot arm only

  The functions under "the maker path" below rest a **post-only limit** (`timeInForce=GTX`)
  at the touch on our side — a buy at the best bid, a sell at the best ask, the touch read
  from the trading host's `bookTicker` at the decision tick — for **W seconds** (60; the
  caller's), then cancel whatever is unfilled and cross the remainder with a `MARKET`. No
  re-pegging. A GTX the exchange refuses (our price would cross: the market has moved
  through our side, `-5022` or an `EXPIRED` answer) is crossed at once and recorded
  `rejected_then_crossed`. Each leg comes back with what was rested, how long, the realised
  VWAP, the quantity, and its realised fee in bps (maker 2.0 / taker 5.0 per side, weighted
  by the filled quantities) — the fields S2 reads. The pieces are separate (`place_resting/6`,
  `settle_resting/8`, `cross_now/6`) because the executor must not block for W: it places,
  writes the row, and settles in a task; `maker_open/4` and `maker_close/3` compose them
  synchronously for `mix flux.testnet_smoke --maker`. M3-4's objection to resting (§3 of
  M3_5_INTEGRATION) stands for the paper arms, which never come here; M1 measured the path
  on this policy's own trades and found +3 bps, and M2 is the live measurement of that.
  """
  require Logger

  alias FluxTrader.Binance.Filters
  alias FluxTrader.Trading.ExecCost

  @terminal ~w(FILLED CANCELED EXPIRED REJECTED EXPIRED_IN_MATCH)
  @poll_attempts 10
  @poll_ms 200

  @typedoc "What a filled order comes back as."
  @type fill :: %{
          order_id: integer(),
          status: String.t(),
          avg_price: float(),
          executed_qty: float()
        }

  @doc "Fetch and parse the trading host's symbol filters."
  def load_filters(client) do
    case client.exchange_info() do
      {:ok, info} -> {:ok, Filters.from_exchange_info(info)}
      {:error, reason} -> {:error, {:exchange_info, reason}}
    end
  end

  @doc """
  Open a position. `req` needs `symbol`, `side` (`"BUY"`/`"SELL"`), `quantity`, `price`
  (for the notional check), `leverage`, `stop_loss` and `take_profit` (prices).

  Returns `{:ok, fill}` with `stop_order_id` / `target_order_id` merged in (either may be
  nil if that brake failed to place), or `{:error, reason}` with nothing on the exchange.
  """
  def open(client, filters, req) do
    with {:ok, f} <- symbol_filters(filters, req.symbol),
         {:ok, qty} <- Filters.sized_qty(f, req.quantity, req.price),
         :ok <- ensure_leverage(client, req.symbol, req.leverage),
         {:ok, fill} <- market(client, req.symbol, req.side, qty, false) do
      {:ok, Map.merge(fill, place_brakes(client, f, req, fill))}
    end
  end

  @doc """
  Close a position. `req` needs `symbol`, `side` (the CLOSING side), `quantity` (what was
  filled at entry), and the `stop_order_id` / `target_order_id` to read back if the exchange
  says there is nothing left to close.

  Returns `{:ok, fill}` with `exit_reason` (`"timer"`, `"stop"` or `"target"`), or
  `{:error, :position_missing}` / `{:error, reason}`.
  """
  def close(client, req) do
    cancel_brakes(client, req.symbol)

    case market(client, req.symbol, req.side, req.quantity, true) do
      {:ok, fill} ->
        {:ok, Map.put(fill, :exit_reason, "timer")}

      {:error, {_status, %{"code" => -2022}}} ->
        brake_exit(client, req)

      other ->
        other
    end
  end

  @doc "Cancel every resting order and algo order on the symbol. Errors are logged, not raised."
  def cancel_brakes(client, symbol) do
    for {what, fun} <- [{"cancel_all", &client.cancel_all_open_orders/1},
                        {"cancel_all_algo", &client.cancel_all_algo_orders/1}] do
      case fun.(symbol) do
        {:ok, _} -> :ok
        # -2011 "Unknown order sent" — nothing resting, which is fine.
        {:error, reason} -> Logger.warning("[AUTO] #{what} on #{symbol}: #{inspect(reason)}")
      end
    end

    :ok
  end

  @doc "Which brake, if any, closed the position — read back from the exchange."
  def brake_exit(client, req) do
    Enum.find_value([{"stop", req[:stop_order_id]}, {"target", req[:target_order_id]}], fn
      {_reason, nil} ->
        nil

      {reason, algo_id} ->
        case triggered_order(client, req.symbol, algo_id) do
          {:ok, fill} -> {:ok, Map.put(fill, :exit_reason, reason)}
          _ -> nil
        end
    end) || {:error, :position_missing}
  end

  @doc """
  The fill behind a brake algo, if it has triggered: `{:ok, fill}` with the normal order's
  id and fill, `:not_triggered`, or `{:error, reason}`.
  """
  def triggered_order(client, symbol, algo_id) do
    with {:ok, algo} <- client.get_algo_order(symbol, algo_id),
         actual when is_integer(actual) and actual > 0 <- to_i(algo["actualOrderId"]),
         {:ok, %{"status" => "FILLED"} = order} <- client.get_order(symbol, actual) do
      fill_from(order)
    else
      {:ok, _not_filled_order} -> :not_triggered
      {:error, reason} -> {:error, reason}
      _ -> :not_triggered
    end
  end

  @doc "Whether `order_id` is the triggered order of one of `algo_ids` — `{:ok, index}` or `:none`."
  def which_brake(client, symbol, order_id, algo_ids) do
    Enum.find_value(Enum.with_index(algo_ids), :none, fn
      {nil, _i} ->
        nil

      {algo_id, i} ->
        case client.get_algo_order(symbol, algo_id) do
          {:ok, algo} -> if to_i(algo["actualOrderId"]) == order_id, do: {:ok, i}, else: nil
          _ -> nil
        end
    end)
  end

  # ------------------------------------------------------------------ the maker path (M2)

  @maker_poll_ms 2_000
  @gtx_reject_code -5022
  @rejected ~w(EXPIRED REJECTED EXPIRED_IN_MATCH)

  @typedoc """
  One settled leg of the maker path. `order_type` is `maker` (rested and filled in full),
  `maker_partial` (part filled at the rest; the remainder was under the exchange's minimum
  order and is left), `maker_then_taker` (unfilled or part filled at W; the remainder crossed)
  or `rejected_then_crossed`. `fill_price` is the realised VWAP over both parts; `order_id` the
  order that filled the larger part; `fee_bps` the leg's realised fee in bps of notional.
  """
  @type leg :: %{
          order_type: String.t(),
          rest_price: float() | nil,
          wait_s: float(),
          fill_price: float(),
          executed_qty: float(),
          fee_bps: float(),
          order_id: integer(),
          limit_order_id: integer() | nil,
          touch_bid: float(),
          touch_ask: float(),
          status: String.t()
        }

  @doc "Size the entry and set its leverage without placing anything: `{:ok, f, qty}`."
  def prepare_open(client, filters, req) do
    with {:ok, f} <- symbol_filters(filters, req.symbol),
         {:ok, qty} <- Filters.sized_qty(f, req.quantity, req.price),
         :ok <- ensure_leverage(client, req.symbol, req.leverage) do
      {:ok, f, qty}
    end
  end

  @doc "The best bid and ask on the trading host, as floats."
  def touch(client, symbol) do
    case client.book_ticker(symbol) do
      {:ok, %{"bidPrice" => b, "askPrice" => a} = t} ->
        bid = to_f(b)
        ask = to_f(a)

        if bid > 0.0 and ask > 0.0,
          do: {:ok, %{bid: bid, ask: ask, bid_qty: to_f(t["bidQty"]), ask_qty: to_f(t["askQty"])}},
          else: {:error, {:no_touch, t}}

      {:ok, other} -> {:error, {:no_touch, other}}
      {:error, reason} -> {:error, {:book_ticker, reason}}
    end
  end

  @doc """
  Rest a post-only limit at the touch on our side: `{:resting, resting}` (the order is on the
  book — settle it with `settle_resting/8`), `{:rejected, touch}` (GTX refused: cross now), or
  `{:error, reason}` with nothing on the exchange.
  """
  def place_resting(client, f, symbol, side, qty, reduce_only?) do
    with {:ok, touch} <- touch(client, symbol) do
      rest = Filters.round_price(f, if(side == "BUY", do: touch.bid, else: touch.ask))

      params =
        [
          symbol: symbol,
          side: side,
          type: "LIMIT",
          timeInForce: "GTX",
          quantity: num(qty),
          price: num(rest),
          newOrderRespType: "RESULT"
        ] ++ if(reduce_only?, do: [reduceOnly: "true"], else: [])

      case client.place_order(params) do
        {:ok, %{"status" => st}} when st in @rejected ->
          {:rejected, touch}

        {:ok, %{"orderId" => id} = resp} ->
          {:resting,
           %{
             order_id: id,
             rest_price: rest,
             touch: touch,
             placed_at_ms: System.monotonic_time(:millisecond),
             status: resp["status"]
           }}

        {:ok, other} ->
          {:error, {:unexpected_response, other}}

        {:error, {_status, %{"code" => @gtx_reject_code}}} ->
          {:rejected, touch}

        {:error, reason} ->
          {:error, reason}
      end
    end
  end

  @doc """
  Wait for the resting order to fill, up to `wait_s` after it was placed (less whatever has
  already elapsed), polling `GET /order`; at the deadline cancel it and cross the remainder
  with a `MARKET` (`reduce_only?` as the leg). Returns `{:ok, leg}`; `{:error, reason}` only
  when nothing filled and the crossing order failed too (the raw exchange error is kept so a
  `-2022` on an exit can be read as "a brake fired first").
  """
  def settle_resting(client, f, symbol, side, qty, resting, wait_s, reduce_only?) do
    deadline = resting.placed_at_ms + round(wait_s * 1_000)
    poll_resting(client, f, symbol, side, qty, resting, deadline, reduce_only?)
  end

  defp poll_resting(client, f, symbol, side, qty, resting, deadline, reduce_only?) do
    now = System.monotonic_time(:millisecond)

    case client.get_order(symbol, resting.order_id) do
      {:ok, %{"status" => "FILLED"} = order} ->
        {:ok, maker_leg(resting, order, now, f)}

      {:ok, %{"status" => st} = order} when st in ["CANCELED" | @rejected] ->
        # Cancelled or expired under us (an operator, the exchange): take what filled, cross the rest.
        finish_leg(client, f, symbol, side, qty, resting, order, now, reduce_only?)

      {:ok, order} when now >= deadline ->
        cancel_and_finish(client, f, symbol, side, qty, resting, order, reduce_only?)

      {:ok, _order} ->
        Process.sleep(min(@maker_poll_ms, max(deadline - now, 0)) |> max(10))
        poll_resting(client, f, symbol, side, qty, resting, deadline, reduce_only?)

      {:error, reason} ->
        Logger.warning("[MAKER] #{symbol} order #{resting.order_id}: read-back failed (#{inspect(reason)})")

        if now >= deadline do
          cancel_and_finish(client, f, symbol, side, qty, resting, %{}, reduce_only?)
        else
          Process.sleep(@maker_poll_ms)
          poll_resting(client, f, symbol, side, qty, resting, deadline, reduce_only?)
        end
    end
  end

  defp cancel_and_finish(client, f, symbol, side, qty, resting, last_seen, reduce_only?) do
    now = System.monotonic_time(:millisecond)

    final =
      case client.cancel_order(symbol, resting.order_id) do
        {:ok, %{"orderId" => _} = resp} ->
          resp

        # -2011 "Unknown order sent": it is no longer open — filled in the last moment, most
        # likely. Read it back rather than assume.
        {:error, reason} ->
          Logger.info("[MAKER] #{symbol} cancel of #{resting.order_id} answered #{inspect(reason)} — reading the order back")

          case client.get_order(symbol, resting.order_id) do
            {:ok, order} -> order
            _ -> last_seen
          end
      end

    finish_leg(client, f, symbol, side, qty, resting, final, now, reduce_only?)
  end

  # The rest is over: `order` is its final state. Keep what filled at the rest price and
  # cross the remainder, unless the remainder is too small to be an order on its own.
  defp finish_leg(client, f, symbol, side, qty, resting, order, now, reduce_only?) do
    filled = to_f(order["executedQty"])
    rest_px = if filled > 0.0 and to_f(order["avgPrice"]) > 0.0, do: to_f(order["avgPrice"]), else: resting.rest_price
    remainder = Filters.round_qty(f, max(qty - filled, 0.0))
    wait_s = (now - resting.placed_at_ms) / 1_000

    cond do
      remainder <= 0.0 and filled > 0.0 ->
        {:ok, maker_leg(resting, order, now, f)}

      filled > 0.0 and not reduce_only? and remainder * rest_px < f.min_notional ->
        # An entry remainder under the exchange's minimum order cannot be sent (-4164); the
        # position is the part that filled. The exit will close exactly that quantity.
        Logger.warning(
          "[MAKER] #{symbol}: #{filled} filled at the rest, remainder #{remainder} is under the " <>
            "minimum order — keeping the partial position (maker_partial)"
        )

        {:ok,
         %{
           order_type: "maker_partial",
           rest_price: resting.rest_price,
           wait_s: wait_s,
           fill_price: rest_px,
           executed_qty: filled,
           fee_bps: ExecCost.maker_fee_bps_per_side(),
           order_id: resting.order_id,
           limit_order_id: resting.order_id,
           touch_bid: resting.touch.bid,
           touch_ask: resting.touch.ask,
           status: order["status"] || "CANCELED"
         }}

      true ->
        case market(client, symbol, side, remainder, reduce_only?) do
          {:ok, fill} ->
            total = filled + fill.executed_qty
            maker_fee = ExecCost.maker_fee_bps_per_side()
            taker_fee = ExecCost.taker_fee_bps_per_side()

            {:ok,
             %{
               order_type: "maker_then_taker",
               rest_price: resting.rest_price,
               wait_s: wait_s,
               fill_price: (filled * rest_px + fill.executed_qty * fill.avg_price) / total,
               executed_qty: total,
               fee_bps: (filled * maker_fee + fill.executed_qty * taker_fee) / total,
               order_id: if(fill.executed_qty >= filled, do: fill.order_id, else: resting.order_id),
               limit_order_id: resting.order_id,
               touch_bid: resting.touch.bid,
               touch_ask: resting.touch.ask,
               status: fill.status
             }}

          {:error, reason} when filled > 0.0 ->
            # The crossing order failed but part of the leg is on the book as a position:
            # report that part as the leg rather than lose it.
            Logger.error("[MAKER] #{symbol}: crossing the remainder #{remainder} FAILED (#{inspect(reason)}) — the leg is the #{filled} that filled at the rest")

            {:ok,
             %{
               order_type: "maker_partial",
               rest_price: resting.rest_price,
               wait_s: wait_s,
               fill_price: rest_px,
               executed_qty: filled,
               fee_bps: ExecCost.maker_fee_bps_per_side(),
               order_id: resting.order_id,
               limit_order_id: resting.order_id,
               touch_bid: resting.touch.bid,
               touch_ask: resting.touch.ask,
               status: order["status"] || "CANCELED"
             }}

          {:error, reason} ->
            {:error, reason}
        end
    end
  end

  defp maker_leg(resting, order, now, _f) do
    %{
      order_type: "maker",
      rest_price: resting.rest_price,
      wait_s: (now - resting.placed_at_ms) / 1_000,
      fill_price: if(to_f(order["avgPrice"]) > 0.0, do: to_f(order["avgPrice"]), else: resting.rest_price),
      executed_qty: to_f(order["executedQty"]),
      fee_bps: ExecCost.maker_fee_bps_per_side(),
      order_id: resting.order_id,
      limit_order_id: resting.order_id,
      touch_bid: resting.touch.bid,
      touch_ask: resting.touch.ask,
      status: "FILLED"
    }
  end

  @doc "GTX refused: cross at once. The leg is `rejected_then_crossed` with the touch it was refused at."
  def cross_now(client, symbol, side, qty, touch, reduce_only?) do
    with {:ok, fill} <- market(client, symbol, side, qty, reduce_only?) do
      {:ok,
       %{
         order_type: "rejected_then_crossed",
         rest_price: if(side == "BUY", do: touch.bid, else: touch.ask),
         wait_s: 0.0,
         fill_price: fill.avg_price,
         executed_qty: fill.executed_qty,
         fee_bps: ExecCost.taker_fee_bps_per_side(),
         order_id: fill.order_id,
         limit_order_id: nil,
         touch_bid: touch.bid,
         touch_ask: touch.ask,
         status: fill.status
       }}
    end
  end

  @doc """
  The maker path's entry, synchronously: size, lever, rest for `wait_s`, cross the remainder,
  brake the position. `{:ok, fill}` is `open/3`'s shape plus the leg's fields; the brakes
  are placed on the filled quantity, after the leg settles.
  """
  def maker_open(client, filters, req, wait_s) do
    with {:ok, f, qty} <- prepare_open(client, filters, req),
         {:ok, leg} <- maker_entry_leg(client, f, req.symbol, req.side, qty, wait_s) do
      fill = fill_of_leg(leg)
      {:ok, Map.merge(fill, place_brakes(client, f, req, fill))}
    end
  end

  @doc "Place and settle an entry leg (no brakes) — the executor's task runs this after writing the row."
  def maker_entry_leg(client, f, symbol, side, qty, wait_s) do
    case place_resting(client, f, symbol, side, qty, false) do
      {:resting, resting} -> settle_resting(client, f, symbol, side, qty, resting, wait_s, false)
      {:rejected, touch} -> cross_now(client, symbol, side, qty, touch, false)
      {:error, reason} -> {:error, reason}
    end
  end

  @doc """
  The maker path's exit, synchronously: cancel the brakes, rest a reduce-only limit at the
  touch for `wait_s`, cross the remainder. `{:ok, fill}` is `close/2`'s shape plus the leg's
  fields; `-2022` anywhere on the way means a brake fired first (`brake_exit/2`).
  """
  def maker_close(client, filters, req, wait_s) do
    cancel_brakes(client, req.symbol)

    with {:ok, f} <- symbol_filters(filters, req.symbol) do
      case maker_exit_leg(client, f, req.symbol, req.side, req.quantity, wait_s) do
        {:ok, leg} -> {:ok, Map.put(fill_of_leg(leg), :exit_reason, "timer")}
        {:error, {_status, %{"code" => -2022}}} -> brake_exit(client, req)
        other -> other
      end
    end
  end

  @doc "Place and settle an exit leg (reduce-only); the brakes must already be cancelled."
  def maker_exit_leg(client, f, symbol, side, qty, wait_s) do
    case place_resting(client, f, symbol, side, qty, true) do
      {:resting, resting} -> settle_resting(client, f, symbol, side, qty, resting, wait_s, true)
      {:rejected, touch} -> cross_now(client, symbol, side, qty, touch, true)
      {:error, reason} -> {:error, reason}
    end
  end

  @doc "A settled leg as `open/3`'s fill map, the leg's own fields kept beside."
  def fill_of_leg(leg) do
    leg
    |> Map.put(:avg_price, leg.fill_price)
    |> Map.put(:executed_qty, leg.executed_qty)
  end

  # Binance wants plain decimals. Elixir prints an exact round float in scientific notation
  # (`to_string(1200.0) == "1.2e3"`), which the exchange rejects — a DOGE-sized quantity would
  # hit it eventually.
  @doc false
  def num(x) when is_float(x) do
    x
    |> :erlang.float_to_binary(decimals: 8)
    |> String.trim_trailing("0")
    |> String.trim_trailing(".")
  end

  def num(x) when is_integer(x), do: Integer.to_string(x)

  # ------------------------------------------------------------------ pieces

  @doc "The symbol's filters out of `load_filters/1`'s map, or `{:error, {:no_filters_for, symbol}}`."
  def symbol_filters(filters, symbol) do
    case Map.fetch(filters, symbol) do
      {:ok, f} -> {:ok, f}
      :error -> {:error, {:no_filters_for, symbol}}
    end
  end

  defp ensure_leverage(_client, _symbol, nil), do: :ok

  defp ensure_leverage(client, symbol, leverage) do
    case client.set_leverage(symbol, leverage) do
      {:ok, _} -> :ok
      {:error, reason} -> {:error, {:leverage, reason}}
    end
  end

  defp market(client, symbol, side, qty, reduce_only?) do
    params =
      [symbol: symbol, side: side, type: "MARKET", quantity: num(qty), newOrderRespType: "RESULT"] ++
        if(reduce_only?, do: [reduceOnly: "true"], else: [])

    with {:ok, resp} <- client.place_order(params),
         {:ok, final} <- reconcile(client, symbol, resp, @poll_attempts) do
      fill_from(final)
    end
  end

  # The response usually carries the fill already; when it does not, the order's status is
  # read back until it is terminal AND carries the fill. Ten polls at 200ms is two seconds —
  # a MARKET order that has not resolved by then is not going to, and the caller gets the
  # last thing seen.
  #
  # "Terminal" alone is not enough: the demo exchange (2026-09-10, order 28578998606)
  # answered a MARKET order `status: FILLED` with `avgPrice: 0` and `executedQty: 0` in the
  # same response, and only the read-back carried the numbers. A FILLED order with no fill
  # in it is therefore polled like a NEW one.
  defp reconcile(client, symbol, %{"status" => st} = resp, n) when st in @terminal do
    if st == "FILLED" and not filled_fields?(resp) and n > 0,
      do: poll(client, symbol, resp, n),
      else: {:ok, resp}
  end

  defp reconcile(_client, _symbol, resp, 0), do: {:error, {:unreconciled, resp}}
  defp reconcile(client, symbol, %{"orderId" => _} = resp, n), do: poll(client, symbol, resp, n)
  defp reconcile(_client, _symbol, resp, _n), do: {:error, {:unexpected_response, resp}}

  defp poll(client, symbol, %{"orderId" => id}, n) do
    Process.sleep(@poll_ms)

    case client.get_order(symbol, id) do
      {:ok, resp} -> reconcile(client, symbol, resp, n - 1)
      {:error, reason} -> {:error, {:reconcile_failed, reason}}
    end
  end

  defp filled_fields?(order), do: to_f(order["executedQty"]) > 0.0 and to_f(order["avgPrice"]) > 0.0

  defp fill_from(%{"orderId" => id} = order) do
    qty = to_f(order["executedQty"])
    price = to_f(order["avgPrice"])
    status = order["status"]

    if qty > 0.0 and price > 0.0 do
      {:ok, %{order_id: id, status: status, avg_price: price, executed_qty: qty}}
    else
      {:error, {:not_filled, status, id}}
    end
  end

  defp fill_from(other), do: {:error, {:unexpected_response, other}}

  @doc "Attach the stop and target algos to a filled position: `%{stop_order_id, target_order_id}` (either nil if it failed to place)."
  def place_brakes(client, f, req, fill) do
    closing = if req.side == "BUY", do: "SELL", else: "BUY"

    %{
      stop_order_id: brake(client, f, req.symbol, closing, "STOP_MARKET", req[:stop_loss], fill),
      target_order_id:
        brake(client, f, req.symbol, closing, "TAKE_PROFIT_MARKET", req[:take_profit], fill)
    }
  end

  defp brake(_client, _f, _symbol, _side, _type, nil, _fill), do: nil

  defp brake(client, f, symbol, side, type, price, fill) do
    params = [
      algoType: "CONDITIONAL",
      symbol: symbol,
      side: side,
      type: type,
      triggerPrice: Filters.round_price(f, price),
      closePosition: "true",
      workingType: "MARK_PRICE"
    ]

    case client.place_algo_order(params) do
      {:ok, %{"algoId" => id}} ->
        id

      {:error, reason} ->
        Logger.error(
          "[AUTO] #{type} on #{symbol} (order #{fill.order_id}) FAILED — position is " <>
            "UNBRAKED until the timed close: #{inspect(reason)}"
        )

        nil
    end
  end

  defp to_i(nil), do: 0
  defp to_i(v) when is_integer(v), do: v
  defp to_i(v) when is_float(v), do: trunc(v)

  defp to_i(v) when is_binary(v) do
    case Integer.parse(v) do
      {i, _} -> i
      :error -> 0
    end
  end

  defp to_f(nil), do: 0.0
  defp to_f(v) when is_float(v), do: v
  defp to_f(v) when is_integer(v), do: v * 1.0

  defp to_f(v) when is_binary(v) do
    case Float.parse(v) do
      {x, _} -> x
      :error -> 0.0
    end
  end
end
