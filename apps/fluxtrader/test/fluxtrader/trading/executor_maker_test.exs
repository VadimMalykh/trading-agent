defmodule FluxTrader.Trading.ExecutorMakerTest do
  @moduledoc """
  The pilot's maker path (M2) through the executor: the row written at placement, settled by
  the task, the exit resting and booked, the engine-facing answers. Against `Binance.Trade.Fake`;
  the ledger is real. W is 0 here so a rest settles at once; a scripted FILLED read-back makes
  it a maker fill, the fake's default (NEW forever) makes it cancel-and-cross.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Binance.Trade.Fake
  alias FluxTrader.Repo
  alias FluxTrader.Trading.{Executor, Ledger, LivePilot, PaperTrade}

  setup do
    prev = for k <- [:trading, :binance, :trade_client, :live_pilot], do: {k, Application.get_env(:fluxtrader, k)}

    on_exit(fn ->
      for {k, v} <- prev do
        if v == nil, do: Application.delete_env(:fluxtrader, k), else: Application.put_env(:fluxtrader, k, v)
      end

      Fake.stop()
    end)

    Application.put_env(:fluxtrader, :trading, mode: "simulation", leverage: 5, max_leverage: 10)
    Application.put_env(:fluxtrader, :trade_client, Fake)
    Application.put_env(:fluxtrader, :binance, api_key: "k", api_secret: "s", testnet: true)
    Application.put_env(:fluxtrader, :live_pilot, enabled: true, notional_usd: 800.0, maker_path: true, maker_wait_s: 0)
    :ok
  end

  defp decision(pair, side) do
    now = DateTime.utc_now()

    %{
      pair: pair,
      side: side,
      size: 1.0,
      entry_ts: now,
      exit_after_ts: DateTime.add(now, 240 * 60, :second),
      entry_price: 100_000.0,
      confidence: 0.7,
      threshold: 0.63,
      regime: 0.01,
      checkpoint: "abc",
      ladder_p80: 0.025
    }
  end

  defp pilot_order(d) do
    {:ok, order} = LivePilot.check(d)
    order
  end

  defp limit_resting(id), do: {:ok, %{"orderId" => id, "status" => "NEW", "avgPrice" => "0", "executedQty" => "0"}}

  # The settle task reports back through the executor; wait until the row leaves its resting state.
  defp settled(id, field) do
    Enum.reduce_while(1..100, nil, fn _, _ ->
      row = Repo.get(PaperTrade, id)

      if row == nil or Map.get(row, field) != "maker_resting",
        do: {:halt, row},
        else: (Process.sleep(20); {:cont, row})
    end)
  end

  test "entry: the row is written at placement, then rewritten from the settled maker fill with the brakes" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(31)],
          get_order: [{:ok, %{"orderId" => 31, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}}]
        }
      )

    start_supervised!({Executor, []})
    assert Executor.status().maker_path

    d = decision("BTCUSDT", 1)
    assert {:ok, trade} = Executor.open("live", d, pilot_order(d))
    assert trade.fill_source == "exchange" and trade.entry_order_type in ["maker_resting", "maker"]
    assert trade.entry_order_id == 31
    assert trade.entry_rest_price == 99_990.0 and trade.entry_touch_bid == 99_990.0 and trade.entry_touch_ask == 100_010.0

    row = settled(trade.id, :entry_order_type)
    assert row.entry_order_type == "maker"
    assert row.entry_price == 99_990.0 and row.entry_fill_price == 99_990.0
    assert row.quantity == 0.008
    assert_in_delta row.notional, 99_990.0 * 0.008, 1.0e-6
    assert row.entry_fee_bps == 2.0 and row.cost_bps == 7.0
    assert row.entry_wait_s >= 0.0
    assert is_integer(row.stop_order_id) and is_integer(row.target_order_id)
    # the brakes were placed after the fill, on the filled quantity's side
    [{:place_algo_order, [stop]}, _] = Fake.calls(:place_algo_order)
    assert stop[:side] == "SELL"
  end

  test "entry: nothing filled and the crossing order failed — the row is dropped, no position without a row" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(32), {:error, {400, %{"code" => -2019, "msg" => "Margin is insufficient."}}}]
        }
      )

    start_supervised!({Executor, []})
    d = decision("BTCUSDT", 1)
    assert {:ok, trade} = Executor.open("live", d, pilot_order(d))
    assert settled(trade.id, :entry_order_type) == nil
    assert Ledger.open_pairs("live") == MapSet.new()
  end

  test "entry: a refused GTX crosses at once and writes a complete row synchronously" do
    {:ok, _} = Fake.start(responses: %{place_order: [{:error, {400, %{"code" => -5022, "msg" => "post only"}}}]})
    start_supervised!({Executor, []})
    d = decision("BTCUSDT", -1)
    assert {:ok, trade} = Executor.open("live", d, pilot_order(d))
    assert trade.entry_order_type == "rejected_then_crossed"
    assert trade.entry_price == Fake.fill_price() and trade.entry_fee_bps == 5.0 and trade.cost_bps == 10.0
    assert trade.entry_rest_price == 100_010.0
    assert is_integer(trade.stop_order_id)
  end

  test "exit: the close rests reduce-only, answers resting, drops out of the due list, and books when settled" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(41), limit_resting(42)],
          get_order: [
            {:ok, %{"orderId" => 41, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}},
            {:ok, %{"orderId" => 42, "status" => "FILLED", "avgPrice" => "100500.0", "executedQty" => "0.008"}}
          ]
        }
      )

    start_supervised!({Executor, []})
    d = decision("BTCUSDT", 1)
    {:ok, trade} = Executor.open("live", d, pilot_order(d))
    row = settled(trade.id, :entry_order_type)
    assert row.entry_order_type == "maker"

    # make it due
    {:ok, row} = Ledger.update_trade(row, %{exit_after_ts: DateTime.add(DateTime.utc_now(), -60, :second)})
    assert [%PaperTrade{id: id}] = Ledger.due_trades()
    assert id == row.id

    assert {:resting, resting} = Executor.close(row, 100_400.0)
    assert resting.exit_order_type == "maker_resting" and resting.exit_order_id == 42
    assert resting.exit_rest_price == 100_010.0 and resting.exit_rest_at != nil
    assert Ledger.due_trades() == []

    closed = settled(row.id, :exit_order_type)
    assert closed.status == "closed" and closed.exit_reason == "timer"
    assert closed.exit_order_type == "maker" and closed.exit_price == 100_500.0 and closed.exit_fill_price == 100_500.0
    assert closed.exit_fee_bps == 2.0 and closed.cost_bps == 4.0
    assert_in_delta closed.gross_bps, (100_500.0 / 99_990.0 - 1) * 1.0e4, 1.0e-6
    assert_in_delta closed.net_bps, closed.gross_bps - 4.0, 1.0e-9

    assert [{:cancel_all_open_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_open_orders)
    [_, {:place_order, [exit_limit]}] = Fake.calls(:place_order)
    assert exit_limit[:reduceOnly] == "true" and exit_limit[:side] == "SELL" and exit_limit[:timeInForce] == "GTX"
  end

  test "exit: unfilled at W crosses the remainder and books maker_then_taker at the taker fee" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(51)],
          get_order: [{:ok, %{"orderId" => 51, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}}]
        }
      )

    start_supervised!({Executor, []})
    d = decision("BTCUSDT", 1)
    {:ok, trade} = Executor.open("live", d, pilot_order(d))
    row = settled(trade.id, :entry_order_type)
    {:ok, row} = Ledger.update_trade(row, %{exit_after_ts: DateTime.add(DateTime.utc_now(), -60, :second)})

    assert {:resting, _} = Executor.close(row, 100_400.0)
    closed = settled(row.id, :exit_order_type)
    assert closed.status == "closed" and closed.exit_order_type == "maker_then_taker"
    assert closed.exit_price == Fake.fill_price() and closed.exit_fee_bps == 5.0 and closed.cost_bps == 7.0
    assert [{:cancel_order, ["BTCUSDT", _]}] = Fake.calls(:cancel_order)
  end

  test "exit: -2022 on the rest means a brake fired during the hold — booked from the brake, not guessed" do
    {:ok, _} =
      Fake.start(
        responses: %{
          place_order: [limit_resting(61), {:error, {400, %{"code" => -2022, "msg" => "ReduceOnly Order is rejected."}}}],
          get_order: [{:ok, %{"orderId" => 61, "status" => "FILLED", "avgPrice" => "99990.0", "executedQty" => "0.008"}}],
          # stop algo: never triggered; target algo: triggered, order 99 filled
          get_algo_order: [
            {:ok, %{"algoId" => 1, "algoStatus" => "CANCELED", "actualOrderId" => 0}},
            {:ok, %{"algoId" => 2, "algoStatus" => "FINISHED", "actualOrderId" => 99}}
          ]
        }
      )

    start_supervised!({Executor, []})
    d = decision("BTCUSDT", 1)
    {:ok, trade} = Executor.open("live", d, pilot_order(d))
    row = settled(trade.id, :entry_order_type)
    # the brakes placed by the settle are algos 1 and 2 (the fake numbers calls); point the row at them explicitly
    {:ok, row} = Ledger.update_trade(row, %{exit_after_ts: DateTime.add(DateTime.utc_now(), -60, :second), stop_order_id: 1, target_order_id: 2})
    Fake.start(responses: %{
      place_order: [{:error, {400, %{"code" => -2022, "msg" => "ReduceOnly Order is rejected."}}}],
      get_algo_order: [
        {:ok, %{"algoId" => 1, "algoStatus" => "CANCELED", "actualOrderId" => 0}},
        {:ok, %{"algoId" => 2, "algoStatus" => "FINISHED", "actualOrderId" => 99}}
      ],
      get_order: [{:ok, %{"orderId" => 99, "status" => "FILLED", "avgPrice" => "120000.0", "executedQty" => "0.008"}}]
    })

    assert {:ok, closed} = Executor.close(row, 100_400.0)
    assert closed.exit_reason == "target" and closed.exit_price == 120_000.0 and closed.exit_order_type == nil
  end

  test "the paper arms never take the maker path, whatever the flag says" do
    {:ok, _} = Fake.start()
    start_supervised!({Executor, []})
    assert {:ok, trade} = Executor.open("policy", decision("BTCUSDT", 1))
    assert trade.fill_source == "paper" and trade.entry_order_type == nil
    assert Fake.calls() == []
  end
end
