defmodule FluxTrader.Trading.ExecutorAutoTest do
  @moduledoc """
  The `auto` mode: what the executor does with a real fill, and what it refuses to do
  without a credential. Runs against `Binance.Trade.Fake`; the ledger is real.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Binance.Trade.Fake
  alias FluxTrader.Trading.{ExecCost, Executor, Ledger, RiskManager}

  setup do
    prev_trading = Application.get_env(:fluxtrader, :trading, [])
    prev_binance = Application.get_env(:fluxtrader, :binance, [])
    prev_client = Application.get_env(:fluxtrader, :trade_client)

    on_exit(fn ->
      Application.put_env(:fluxtrader, :trading, prev_trading)
      Application.put_env(:fluxtrader, :binance, prev_binance)
      Application.put_env(:fluxtrader, :trade_client, prev_client)
      Fake.stop()
    end)

    Application.put_env(:fluxtrader, :trading, Keyword.put(prev_trading, :mode, "auto"))
    Application.put_env(:fluxtrader, :trade_client, Fake)
    :ok
  end

  defp with_credentials do
    Application.put_env(:fluxtrader, :binance,
      api_key: "test-key",
      api_secret: "test-secret",
      testnet: true,
      trade_url: "https://demo-fapi.binance.com",
      user_stream_host: "demo-fstream.binance.com"
    )
  end

  defp without_credentials do
    Application.put_env(:fluxtrader, :binance, api_key: nil, api_secret: nil, testnet: false)
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

  defp approved_order(decision) do
    {:ok, order} =
      RiskManager.check(%{
        symbol: decision.pair,
        side: if(decision.side > 0, do: "BUY", else: "SELL"),
        price: decision.entry_price,
        size: decision.size,
        confidence: decision.confidence
      })

    order
  end

  test "auto without credentials is refused, loudly, and runs as simulation" do
    without_credentials()
    start_supervised!({Executor, []})

    assert Executor.mode() == "simulation"
    status = Executor.status()
    assert status.requested_mode == "auto"
    assert status.auto_refused == :missing_credentials
    refute status.live_orders
  end

  test "the policy arm writes the EXCHANGE's fill, fee-only cost, and the order ids" do
    with_credentials()
    {:ok, _} = Fake.start()
    start_supervised!({RiskManager, []})
    start_supervised!({Executor, []})

    assert Executor.mode() == "auto"
    assert Executor.status().testnet

    d = decision("BTCUSDT", 1)
    order = approved_order(d)
    assert {:ok, trade} = Executor.open("policy", d, order)

    assert trade.fill_source == "exchange"
    assert trade.entry_price == Fake.fill_price()
    assert trade.quantity == 0.005
    assert_in_delta trade.notional, Fake.fill_price() * 0.005, 1.0e-6
    assert trade.cost_bps == ExecCost.fee_only_round_trip_bps()
    assert is_integer(trade.entry_order_id)
    assert is_integer(trade.stop_order_id) and is_integer(trade.target_order_id)

    # The brake was placed at the risk manager's prices, rounded to the tick, as algo orders.
    [{:place_algo_order, [stop]}, {:place_algo_order, [target]}] = Fake.calls(:place_algo_order)
    assert stop[:triggerPrice] == Float.round(order.stop_loss, 1)
    assert target[:triggerPrice] == Float.round(order.take_profit, 1)
  end

  test "the control arm never reaches the exchange, whatever the mode" do
    with_credentials()
    {:ok, _} = Fake.start()
    start_supervised!({Executor, []})

    assert {:ok, trade} = Executor.open("flat_size", decision("BTCUSDT", 1))
    assert trade.fill_source == "paper"
    assert trade.entry_price == 100_000.0
    assert trade.cost_bps == ExecCost.cost_bps("BTCUSDT")
    assert Fake.calls() == []
  end

  test "a timed close on an exchange row is a reduceOnly MARKET booked at the real fill" do
    with_credentials()
    {:ok, _} = Fake.start()
    start_supervised!({RiskManager, []})
    start_supervised!({Executor, []})

    d = decision("BTCUSDT", 1)
    {:ok, trade} = Executor.open("policy", d, approved_order(d))

    assert {:ok, closed} = Executor.close(trade, 99_000.0)
    assert closed.exit_reason == "timer"
    assert closed.exit_price == Fake.fill_price()
    assert is_integer(closed.exit_order_id)
    assert_in_delta closed.gross_bps, 0.0, 1.0e-9
    assert_in_delta closed.net_bps, -ExecCost.fee_only_round_trip_bps(), 1.0e-9

    assert [{:cancel_all_open_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_open_orders)
    assert [{:cancel_all_algo_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_algo_orders)
    [_, {:place_order, [close_order]}] = Fake.calls(:place_order)
    assert close_order[:reduceOnly] == "true" and close_order[:side] == "SELL"
    assert close_order[:quantity] == 0.005
  end

  test "a brake fill reported by the user stream closes the row and cancels the sibling" do
    with_credentials()
    {:ok, _} = Fake.start()
    start_supervised!({RiskManager, []})
    start_supervised!({Executor, []})

    d = decision("BTCUSDT", 1)
    {:ok, trade} = Executor.open("policy", d, approved_order(d))
    assert %{open_positions: 1} = RiskManager.get_stats()

    # The stop algo triggered and created order 501, which filled. The stream reports the
    # ORDER; the executor asks the exchange which algo it belongs to.
    Fake.start(
      responses: %{
        get_algo_order: [
          fn _sym, algo_id ->
            {:ok, %{"algoId" => algo_id, "algoStatus" => "FINISHED", "actualOrderId" => 501}}
          end
        ]
      }
    )

    assert {:ok, closed} = Executor.brake_filled("BTCUSDT", 501, 98_000.0)
    assert closed.exit_reason == "stop"
    assert closed.exit_price == 98_000.0
    assert closed.exit_order_id == 501
    assert [{:cancel_all_open_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_open_orders)
    assert [{:cancel_all_algo_orders, ["BTCUSDT"]}] = Fake.calls(:cancel_all_algo_orders)
    assert Ledger.open_trades("policy") == []
    # The slot went back and the loss was booked against the daily limit.
    assert %{open_positions: 0, daily_pnl: pnl} = RiskManager.get_stats()
    assert pnl < 0

    # The timed close that follows must not book the row a second time.
    assert {:error, :already_closed} = Executor.close(trade, 97_000.0)
    # Our own timed close, or a manual one, matches no open row and is ignored.
    assert {:error, :unknown_order} = Executor.brake_filled("BTCUSDT", 999_999, 1.0)
  end
end
