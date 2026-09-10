defmodule FluxTrader.Trading.ExchangeOrdersTest do
  @moduledoc """
  The real order path, against a scripted exchange: sizing, leverage, the fill, the brake,
  reconciliation when the fill is not in the response, and a close that finds the brake
  already fired. Nothing here touches the network or the database.
  """
  use ExUnit.Case, async: false

  alias FluxTrader.Binance.Trade.Fake
  alias FluxTrader.Trading.ExchangeOrders

  setup do
    on_exit(&Fake.stop/0)
    :ok
  end

  defp filters do
    {:ok, f} = ExchangeOrders.load_filters(Fake)
    f
  end

  defp req(overrides \\ %{}) do
    Map.merge(
      %{
        symbol: "BTCUSDT",
        side: "BUY",
        quantity: 0.0083333,
        price: 100_000.0,
        leverage: 5,
        stop_loss: 98_000.04,
        take_profit: 104_000.06
      },
      overrides
    )
  end

  test "open: rounds the quantity down, sets leverage, fills, and attaches both brakes" do
    {:ok, _} = Fake.start()

    assert {:ok, fill} = ExchangeOrders.open(Fake, filters(), req())
    assert fill.avg_price == Fake.fill_price()
    assert fill.executed_qty == 0.008
    assert is_integer(fill.stop_order_id) and is_integer(fill.target_order_id)

    assert [{:set_leverage, ["BTCUSDT", 5]}] = Fake.calls(:set_leverage)

    [{:place_order, [market]}, {:place_order, [stop]}, {:place_order, [target]}] =
      Fake.calls(:place_order)

    assert market[:type] == "MARKET" and market[:quantity] == 0.008
    assert market[:newOrderRespType] == "RESULT"
    refute Keyword.has_key?(market, :reduceOnly)

    assert stop[:type] == "STOP_MARKET" and stop[:side] == "SELL"
    assert stop[:stopPrice] == 98_000.0 and stop[:closePosition] == "true"
    assert stop[:workingType] == "MARK_PRICE"
    assert target[:type] == "TAKE_PROFIT_MARKET" and target[:stopPrice] == 104_000.1
  end

  test "open: a response without the fill is reconciled against GET /order until terminal" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [
            {:ok, %{"orderId" => 7, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}}
          ],
          get_order: [
            {:ok, %{"orderId" => 7, "status" => "PARTIALLY_FILLED", "avgPrice" => "100005", "executedQty" => "0.004"}},
            {:ok, %{"orderId" => 7, "status" => "FILLED", "avgPrice" => "100007.5", "executedQty" => "0.008"}}
          ]
        }
      )

    assert {:ok, fill} = ExchangeOrders.open(Fake, filters(), req())
    assert fill.order_id == 7
    assert fill.avg_price == 100_007.5
    assert fill.executed_qty == 0.008
    assert length(Fake.calls(:get_order)) == 2
  end

  # Seen on the demo exchange 2026-09-10: FILLED in the response, fill fields zero, numbers
  # only on the read-back. Treating "FILLED" as done here left an unbraked position behind.
  test "open: FILLED with zero fill fields is read back until the numbers arrive" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [
            {:ok, %{"orderId" => 11, "status" => "FILLED", "avgPrice" => "0.00", "executedQty" => "0"}}
          ],
          get_order: [
            {:ok, %{"orderId" => 11, "status" => "FILLED", "avgPrice" => "78084.3", "executedQty" => "0.0007"}}
          ]
        }
      )

    assert {:ok, fill} = ExchangeOrders.open(Fake, filters(), req())
    assert fill.order_id == 11
    assert fill.avg_price == 78_084.3
    assert fill.executed_qty == 0.0007
    # ... and the brakes were still attached.
    assert is_integer(fill.stop_order_id) and is_integer(fill.target_order_id)
  end

  test "open: an order that expired unfilled is an error and no brake is placed" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [
            {:ok, %{"orderId" => 9, "status" => "EXPIRED", "avgPrice" => "0", "executedQty" => "0"}}
          ]
        }
      )

    assert {:error, {:not_filled, "EXPIRED", 9}} = ExchangeOrders.open(Fake, filters(), req())
    assert length(Fake.calls(:place_order)) == 1
  end

  test "open: below the minimum notional nothing is sent at all" do
    {:ok, _} = Fake.start()
    # 0.0015 rounds down to one lot (0.001), which at $90k is $90 — under the $100 floor.
    assert {:error, :below_min_notional} =
             ExchangeOrders.open(Fake, filters(), req(%{quantity: 0.0015, price: 90_000.0}))
    assert Fake.calls(:place_order) == []
    assert Fake.calls(:set_leverage) == []
  end

  test "open: a brake that fails to place is nil, and the position is kept" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [
            {:ok, %{"orderId" => 1, "status" => "FILLED", "avgPrice" => "100010", "executedQty" => "0.008"}},
            {:error, {400, %{"code" => -2021, "msg" => "Order would immediately trigger."}}}
          ]
        }
      )

    assert {:ok, fill} = ExchangeOrders.open(Fake, filters(), req())
    assert fill.stop_order_id == nil
    assert is_integer(fill.target_order_id)
  end

  test "close: cancels the brakes, then a reduceOnly MARKET, booked as the timer exit" do
    {:ok, _} = Fake.start()

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:ok, fill} = ExchangeOrders.close(Fake, close)
    assert fill.exit_reason == "timer"
    assert fill.executed_qty == 0.008

    assert [{:cancel_all_open_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_open_orders)
    [{:place_order, [market]}] = Fake.calls(:place_order)
    assert market[:reduceOnly] == "true" and market[:side] == "SELL"
  end

  test "close: -2022 means a brake fired first — the exit comes from whichever one filled" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [
            {:error, {400, %{"code" => -2022, "msg" => "ReduceOnly Order is rejected."}}}
          ],
          get_order: [
            # stop (id 2): not filled; target (id 3): filled
            {:ok, %{"orderId" => 2, "status" => "CANCELED", "avgPrice" => "0", "executedQty" => "0"}},
            {:ok, %{"orderId" => 3, "status" => "FILLED", "avgPrice" => "104000.1", "executedQty" => "0.008"}}
          ]
        }
      )

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:ok, fill} = ExchangeOrders.close(Fake, close)
    assert fill.exit_reason == "target"
    assert fill.avg_price == 104_000.1
    assert fill.order_id == 3
  end

  test "close: -2022 with neither brake filled is position_missing, never a guessed price" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [{:error, {400, %{"code" => -2022, "msg" => "ReduceOnly Order is rejected."}}}]
        }
      )

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:error, :position_missing} = ExchangeOrders.close(Fake, close)
  end
end
