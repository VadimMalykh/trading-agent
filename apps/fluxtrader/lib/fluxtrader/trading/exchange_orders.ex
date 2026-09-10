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
  """
  require Logger

  alias FluxTrader.Binance.Filters

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

  # ------------------------------------------------------------------ pieces

  defp symbol_filters(filters, symbol) do
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
      [symbol: symbol, side: side, type: "MARKET", quantity: qty, newOrderRespType: "RESULT"] ++
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

  defp place_brakes(client, f, req, fill) do
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
