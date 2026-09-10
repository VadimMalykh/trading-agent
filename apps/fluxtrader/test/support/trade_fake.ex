defmodule FluxTrader.Binance.Trade.Fake do
  @moduledoc """
  A scripted `Binance.Trade` for tests — records every call, answers from a queue.

  `start/1` takes `responses: %{callback => [response | fun]}`; each call to a callback
  pops the next entry (a function is applied to the call's arguments). When the queue for a
  callback is empty the default below answers, which is a healthy exchange: every MARKET
  order fills at `@fill_price`, every brake is accepted as NEW, every position is flat.
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

  def stop, do: if(Process.whereis(__MODULE__), do: Agent.stop(__MODULE__))

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
  def get_order(symbol, order_id), do: answer(:get_order, [symbol, order_id])

  @impl true
  def cancel_all_open_orders(symbol), do: answer(:cancel_all_open_orders, [symbol])

  @impl true
  def position_risk(symbol), do: answer(:position_risk, [symbol])

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

  defp default(:get_order, [symbol, order_id], _),
    do: {:ok, %{"orderId" => order_id, "symbol" => symbol, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}}

  defp default(:cancel_all_open_orders, _, _), do: {:ok, %{"code" => 200, "msg" => "ok"}}
  defp default(:position_risk, [symbol], _), do: {:ok, [%{"symbol" => symbol, "positionAmt" => "0", "markPrice" => "100000.0"}]}
  defp default(:commission_rate, [symbol], _), do: {:ok, %{"symbol" => symbol, "makerCommissionRate" => "0.000200", "takerCommissionRate" => "0.000500"}}
  defp default(:listen_key, _, _), do: {:ok, %{"listenKey" => "fake-listen-key"}}
  defp default(:keepalive_listen_key, _, _), do: {:ok, %{}}
end
