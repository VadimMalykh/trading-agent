defmodule FluxTrader.Binance.Trade.Fake do
  @moduledoc """
  A scripted `Binance.Trade` for tests — records every call, answers from a queue.

  `start/1` takes `responses: %{callback => [response | fun]}`; each call to a callback
  pops the next entry (a function is applied to the call's arguments). When the queue for a
  callback is empty the default below answers, which is a healthy exchange: every MARKET
  order fills at `@fill_price`, every LIMIT order rests as NEW and stays unfilled (so the
  maker path's default outcome is cancel-and-cross), the touch is 99,990 / 100,010, every
  brake is accepted as NEW, every position is flat.
  """
  @behaviour FluxTrader.Binance.Trade

  @fill_price 100_010.0

  def start(opts \\ []) do
    responses = Keyword.get(opts, :responses, %{})

    case Agent.start_link(fn -> %{responses: responses, calls: [], next_id: 1} end, name: __MODULE__) do
      {:ok, pid} -> {:ok, pid}
      {:error, {:already_started, pid}} -> Agent.update(pid, fn _ -> %{responses: responses, calls: [], next_id: 1} end); {:ok, pid}
    end
  end

  # The agent is linked to the test process and may already be gone when on_exit runs.
  def stop do
    if pid = Process.whereis(__MODULE__) do
      try do
        Agent.stop(pid)
      catch
        :exit, _ -> :ok
      end
    end

    :ok
  end

  @doc "Every call so far, oldest first, as `{callback, args}`."
  def calls, do: Agent.get(__MODULE__, &Enum.reverse(&1.calls))

  def calls(name), do: calls() |> Enum.filter(&(elem(&1, 0) == name))

  def fill_price, do: @fill_price

  # -------------------------------------------------------------- behaviour

  @impl true
  def exchange_info, do: answer(:exchange_info, [])

  @impl true
  def set_leverage(symbol, leverage), do: answer(:set_leverage, [symbol, leverage])

  @impl true
  def place_order(params), do: answer(:place_order, [params])

  @impl true
  def place_algo_order(params), do: answer(:place_algo_order, [params])

  @impl true
  def get_algo_order(symbol, algo_id), do: answer(:get_algo_order, [symbol, algo_id])

  @impl true
  def cancel_all_algo_orders(symbol), do: answer(:cancel_all_algo_orders, [symbol])

  @impl true
  def get_order(symbol, order_id), do: answer(:get_order, [symbol, order_id])

  @impl true
  def cancel_all_open_orders(symbol), do: answer(:cancel_all_open_orders, [symbol])

  @impl true
  def cancel_order(symbol, order_id), do: answer(:cancel_order, [symbol, order_id])

  @impl true
  def book_ticker(symbol), do: answer(:book_ticker, [symbol])

  @impl true
  def position_risk(symbol), do: answer(:position_risk, [symbol])

  @impl true
  def mark_price(symbol), do: answer(:mark_price, [symbol])

  @impl true
  def commission_rate(symbol), do: answer(:commission_rate, [symbol])

  @impl true
  def listen_key, do: answer(:listen_key, [])

  @impl true
  def keepalive_listen_key, do: answer(:keepalive_listen_key, [])

  # -------------------------------------------------------------- scripting

  defp answer(name, args) do
    {scripted, id} =
      Agent.get_and_update(__MODULE__, fn state ->
        {head, rest} =
          case Map.get(state.responses, name, []) do
            [h | t] -> {h, t}
            [] -> {:default, []}
          end

        {{head, state.next_id},
         %{
           state
           | responses: Map.put(state.responses, name, rest),
             calls: [{name, args} | state.calls],
             next_id: state.next_id + 1
         }}
      end)

    case scripted do
      :default -> default(name, args, id)
      fun when is_function(fun) -> apply(fun, args)
      term -> term
    end
  end

  defp default(:exchange_info, _, _) do
    {:ok,
     %{
       "symbols" => [
         %{
           "symbol" => "BTCUSDT",
           "quantityPrecision" => 3,
           "pricePrecision" => 1,
           "filters" => [
             %{"filterType" => "LOT_SIZE", "stepSize" => "0.001"},
             %{"filterType" => "PRICE_FILTER", "tickSize" => "0.10"},
             %{"filterType" => "MIN_NOTIONAL", "notional" => "100"}
           ]
         }
       ]
     }}
  end

  defp default(:set_leverage, [symbol, lev], _), do: {:ok, %{"symbol" => symbol, "leverage" => lev}}

  defp default(:place_order, [params], id) do
    case Keyword.get(params, :type) do
      "MARKET" ->
        {:ok,
         %{
           "orderId" => id,
           "symbol" => Keyword.get(params, :symbol),
           "status" => "FILLED",
           "type" => "MARKET",
           "avgPrice" => Float.to_string(@fill_price),
           "executedQty" => to_string(Keyword.get(params, :quantity))
         }}

      type ->
        {:ok, %{"orderId" => id, "status" => "NEW", "type" => type}}
    end
  end

  defp default(:place_algo_order, [params], id),
    do: {:ok, %{"algoId" => id, "algoStatus" => "NEW", "symbol" => Keyword.get(params, :symbol),
                "triggerPrice" => to_string(Keyword.get(params, :triggerPrice)), "actualOrderId" => 0}}

  defp default(:get_algo_order, [symbol, algo_id], _),
    do: {:ok, %{"algoId" => algo_id, "symbol" => symbol, "algoStatus" => "NEW", "actualOrderId" => 0}}

  defp default(:cancel_all_algo_orders, _, _), do: {:ok, %{"code" => 200, "msg" => "ok"}}

  defp default(:get_order, [symbol, order_id], _),
    do: {:ok, %{"orderId" => order_id, "symbol" => symbol, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}}

  defp default(:cancel_all_open_orders, _, _), do: {:ok, %{"code" => 200, "msg" => "ok"}}

  # A resting order cancelled unfilled; the answer carries the final fill fields like GET /order.
  defp default(:cancel_order, [symbol, order_id], _),
    do: {:ok, %{"orderId" => order_id, "symbol" => symbol, "status" => "CANCELED", "avgPrice" => "0", "executedQty" => "0"}}

  # The touch: a 20-dollar spread around the fake's fill price, so a rest at the bid is visibly
  # cheaper than the fill a market order gets.
  defp default(:book_ticker, [symbol], _),
    do: {:ok, %{"symbol" => symbol, "bidPrice" => "99990.0", "bidQty" => "5.0", "askPrice" => "100010.0", "askQty" => "3.0"}}
  defp default(:position_risk, [symbol], _), do: {:ok, [%{"symbol" => symbol, "positionAmt" => "0", "markPrice" => "100000.0"}]}
  defp default(:mark_price, [symbol], _), do: {:ok, %{"symbol" => symbol, "markPrice" => "100000.0"}}
  defp default(:commission_rate, [symbol], _), do: {:ok, %{"symbol" => symbol, "makerCommissionRate" => "0.000200", "takerCommissionRate" => "0.000500"}}
  defp default(:listen_key, _, _), do: {:ok, %{"listenKey" => "fake-listen-key"}}
  defp default(:keepalive_listen_key, _, _), do: {:ok, %{}}
end
