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

    [{:place_order, [market]}] = Fake.calls(:place_order)
    assert market[:type] == "MARKET" and market[:quantity] == "0.008"
    assert market[:newOrderRespType] == "RESULT"
    refute Keyword.has_key?(market, :reduceOnly)

    # The brake goes through the Algo Order API (-4120 on the plain endpoint, 2026-09-10).
    [{:place_algo_order, [stop]}, {:place_algo_order, [target]}] = Fake.calls(:place_algo_order)
    assert stop[:algoType] == "CONDITIONAL"
    assert stop[:type] == "STOP_MARKET" and stop[:side] == "SELL"
    assert stop[:triggerPrice] == 98_000.0 and stop[:closePosition] == "true"
    assert stop[:workingType] == "MARK_PRICE"
    refute Keyword.has_key?(stop, :quantity)
    assert target[:type] == "TAKE_PROFIT_MARKET" and target[:triggerPrice] == 104_000.1
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
          place_algo_order: [
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
    assert [{:cancel_all_algo_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_algo_orders)
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
          get_algo_order: [
            # stop (algo 2): never triggered; target (algo 3): triggered, created order 77
            {:ok, %{"algoId" => 2, "algoStatus" => "CANCELED", "actualOrderId" => 0}},
            {:ok, %{"algoId" => 3, "algoStatus" => "FINISHED", "actualOrderId" => 77}}
          ],
          get_order: [
            {:ok, %{"orderId" => 77, "status" => "FILLED", "avgPrice" => "104000.1", "executedQty" => "0.008"}}
          ]
        }
      )

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:ok, fill} = ExchangeOrders.close(Fake, close)
    assert fill.exit_reason == "target"
    assert fill.avg_price == 104_000.1
    assert fill.order_id == 77
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

  # ------------------------------------------------------------------ the maker path (M2)

  defp limit_resting(id), do: {:ok, %{"orderId" => id, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}}

  test "maker entry: rests a GTX at the bid, fills at the rest, pays the maker fee, brakes the filled quantity" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(11)],
          get_order: [{:ok, %{"orderId" => 11, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}}]
        }
      )

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 60)
    assert fill.order_type == "maker"
    assert fill.rest_price == 99_990.0 and fill.avg_price == 99_990.0 and fill.fill_price == 99_990.0
    assert fill.executed_qty == 0.008
    assert fill.fee_bps == 2.0
    assert fill.touch_bid == 99_990.0 and fill.touch_ask == 100_010.0
    assert fill.wait_s >= 0.0 and fill.wait_s < 5.0
    assert is_integer(fill.stop_order_id) and is_integer(fill.target_order_id)

    [{:place_order, [limit]}] = Fake.calls(:place_order)
    assert limit[:type] == "LIMIT" and limit[:timeInForce] == "GTX"
    assert limit[:side] == "BUY" and limit[:price] == "99990" and limit[:quantity] == "0.008"
    refute Keyword.has_key?(limit, :reduceOnly)
    assert Fake.calls(:cancel_order) == []
  end

  test "maker entry: unfilled at W is cancelled and crossed; the leg is maker_then_taker at the taker fee" do
    {:ok, _} = Fake.start(responses: %{place_order: [limit_resting(12)]})

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 0)
    assert fill.order_type == "maker_then_taker"
    assert fill.rest_price == 99_990.0
    assert fill.fill_price == Fake.fill_price() and fill.executed_qty == 0.008
    assert fill.fee_bps == 5.0
    assert fill.limit_order_id == 12 and fill.order_id != 12

    assert [{:cancel_order, ["BTCUSDT", 12]}] = Fake.calls(:cancel_order)
    [{:place_order, [limit]}, {:place_order, [market]}] = Fake.calls(:place_order)
    assert limit[:type] == "LIMIT" and market[:type] == "MARKET" and market[:quantity] == "0.008"
  end

  test "maker entry: a part fill at the rest and the remainder crossed give a VWAP and a weighted fee" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(13)],
          cancel_order: [{:ok, %{"orderId" => 13, "status" => "CANCELED", "avgPrice" => "99990.0", "executedQty" => "0.006"}}]
        }
      )

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 0)
    assert fill.order_type == "maker_then_taker"
    assert fill.executed_qty == 0.008
    assert_in_delta fill.fill_price, (0.006 * 99_990.0 + 0.002 * Fake.fill_price()) / 0.008, 1.0e-6
    assert_in_delta fill.fee_bps, (0.006 * 2.0 + 0.002 * 5.0) / 0.008, 1.0e-9
    # the limit filled the larger part, so it is the leg's order id
    assert fill.order_id == 13
    [_, {:place_order, [market]}] = Fake.calls(:place_order)
    assert market[:quantity] == "0.002"
  end

  test "maker entry: a GTX the exchange refuses (-5022) is crossed at once as rejected_then_crossed" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [{:error, {400, %{"code" => -5022, "msg" => "Due to the order could not be executed as maker, the Post Only order will be rejected."}}}]
        }
      )

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 60)
    assert fill.order_type == "rejected_then_crossed"
    assert fill.fill_price == Fake.fill_price() and fill.fee_bps == 5.0 and fill.wait_s == 0.0
    assert fill.rest_price == 99_990.0 and fill.limit_order_id == nil
    [_, {:place_order, [market]}] = Fake.calls(:place_order)
    assert market[:type] == "MARKET"
    assert Fake.calls(:cancel_order) == []
  end

  test "maker entry: an EXPIRED answer to the GTX is the same refusal" do
    {:ok, _} =
      Fake.start(responses: %{place_order: [{:ok, %{"orderId" => 14, "status" => "EXPIRED", "avgPrice" => "0", "executedQty" => "0"}}]})

    assert {:ok, %{order_type: "rejected_then_crossed"}} = ExchangeOrders.maker_open(Fake, filters(), req(), 60)
  end

  test "maker entry: a part fill whose remainder is under the minimum order keeps the partial position" do
    # 0.008 BTC rested; 0.007 filled; the 0.001 left is ~$100 — under the fake's $100 floor at $99,990.
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(15)],
          cancel_order: [{:ok, %{"orderId" => 15, "status" => "CANCELED", "avgPrice" => "99990.0", "executedQty" => "0.007"}}]
        }
      )

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 0)
    assert fill.order_type == "maker_partial"
    assert fill.executed_qty == 0.007 and fill.fill_price == 99_990.0 and fill.fee_bps == 2.0
    assert length(Fake.calls(:place_order)) == 1
  end

  test "maker entry: the cancel racing a last-moment fill reads the order back and keeps the maker fill" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(16)],
          cancel_order: [{:error, {400, %{"code" => -2011, "msg" => "Unknown order sent."}}}],
          get_order: [
            {:ok, %{"orderId" => 16, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}},
            {:ok, %{"orderId" => 16, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}}
          ]
        }
      )

    assert {:ok, fill} = ExchangeOrders.maker_open(Fake, filters(), req(), 0)
    assert fill.order_type == "maker" and fill.fee_bps == 2.0
    assert length(Fake.calls(:place_order)) == 1
  end

  test "maker exit: cancels the brakes, rests a reduce-only GTX at the ask, books the timer exit when it fills" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(21)],
          get_order: [{:ok, %{"orderId" => 21, "status" => "FILLED", "avgPrice" => "100010.0", "executedQty" => "0.008"}}]
        }
      )

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:ok, fill} = ExchangeOrders.maker_close(Fake, filters(), close, 60)
    assert fill.exit_reason == "timer" and fill.order_type == "maker"
    assert fill.avg_price == 100_010.0 and fill.fee_bps == 2.0

    assert [{:cancel_all_open_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_open_orders)
    assert [{:cancel_all_algo_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_algo_orders)
    [{:place_order, [limit]}] = Fake.calls(:place_order)
    assert limit[:timeInForce] == "GTX" and limit[:reduceOnly] == "true" and limit[:price] == "100010"
  end

  test "maker exit: -2022 on the rest means a brake fired first — the exit comes from the brake" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [{:error, {400, %{"code" => -2022, "msg" => "ReduceOnly Order is rejected."}}}],
          get_algo_order: [
            {:ok, %{"algoId" => 2, "algoStatus" => "FINISHED", "actualOrderId" => 78}}
          ],
          get_order: [{:ok, %{"orderId" => 78, "status" => "FILLED", "avgPrice" => "98000.0", "executedQty" => "0.008"}}]
        }
      )

    close = %{symbol: "BTCUSDT", side: "SELL", quantity: 0.008, stop_order_id: 2, target_order_id: 3}
    assert {:ok, fill} = ExchangeOrders.maker_close(Fake, filters(), close, 60)
    assert fill.exit_reason == "stop" and fill.avg_price == 98_000.0
  end

  test "numbers go to the exchange as plain decimals, never in scientific notation" do
    assert ExchangeOrders.num(1200.0) == "1200"
    assert ExchangeOrders.num(0.0047125) == "0.0047125"
    assert ExchangeOrders.num(0.008) == "0.008"
    assert ExchangeOrders.num(84_550.1) == "84550.1"
    assert ExchangeOrders.num(3) == "3"
  end
end
