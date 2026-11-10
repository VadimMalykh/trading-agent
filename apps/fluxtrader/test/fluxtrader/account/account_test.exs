defmodule FluxTrader.Account.AccountTest do
  @moduledoc """
  The account page's arithmetic: flat-to-flat deals from fills, bot/manual by order id, the
  month rows against the notional deposit in force then, the pilot's sizing scaled by the
  deposit, and one sync pass against a stubbed exchange.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Account.{Deals, Fill, Income, NotionalDeposit, Stats, Sync}
  alias FluxTrader.Repo
  alias FluxTrader.Trading.{LivePilot, PaperTrade}

  defp fill(symbol, order_id, side, qty, at, pnl \\ 0.0, fee \\ 0.1, asset \\ "USDT") do
    %{symbol: symbol, order_id: order_id, side: side, qty: qty, realized_pnl: pnl, commission: fee,
      commission_asset: asset, time: at}
  end

  describe "Deals.build/3" do
    test "flat-to-flat: fees of every fill, funding while open, owner by order id" do
      fills = [
        fill("SOLUSDT", 1, "BUY", 2.2, ~U[2026-11-05 16:42:42Z]),
        fill("SOLUSDT", 2, "SELL", 2.2, ~U[2026-11-05 20:42:44Z], -0.946, 0.04),
        fill("SOLUSDT", 3, "BUY", 5.79, ~U[2026-11-08 21:55:16Z])
      ]

      funding = [
        %{symbol: "SOLUSDT", income: -0.02, time: ~U[2026-11-05 16:00:00Z]},
        %{symbol: "SOLUSDT", income: -0.03, time: ~U[2026-11-05 20:00:00Z]},
        %{symbol: "SOLUSDT", income: 0.05, time: ~U[2026-11-09 00:00:00Z]}
      ]

      [closed, open] = Deals.build(fills, funding, MapSet.new([1]))

      assert closed.owner == :bot and closed.side == 1 and closed.closed_at == ~U[2026-11-05 20:42:44Z]
      assert_in_delta closed.net, -0.946 - 0.14 - 0.03, 1.0e-9
      assert open.owner == :manual and open.closed_at == nil and open.qty == 5.79
      assert_in_delta open.funding, 0.05, 1.0e-9
    end

    test "scaling in and out stays one deal; a crossing fill splits its fee" do
      fills = [
        fill("ADAUSDT", 10, "BUY", 1000.0, ~U[2026-11-01 00:00:00Z]),
        fill("ADAUSDT", 11, "BUY", 500.0, ~U[2026-11-02 00:00:00Z]),
        fill("ADAUSDT", 12, "SELL", 700.0, ~U[2026-11-03 00:00:00Z], 5.0),
        # 800 closes, 200 opens a short
        fill("ADAUSDT", 13, "SELL", 1000.0, ~U[2026-11-04 00:00:00Z], 7.0, 1.0)
      ]

      [long, short] = Deals.build(fills)
      assert long.fills == 4 and long.max_qty == 1500.0 and long.pnl == 12.0
      assert_in_delta long.fees, 0.3 + 0.8, 1.0e-9
      assert short.side == -1 and short.closed_at == nil and and_in(short.qty, -200.0)
      assert_in_delta short.fees, 0.2, 1.0e-9
    end

    test "a fee in another asset stays out of net" do
      [d] = Deals.build([fill("X", 1, "BUY", 1.0, ~U[2026-11-01 00:00:00Z], 0.0, 0.001, "BNB"),
                         fill("X", 2, "SELL", 1.0, ~U[2026-11-01 01:00:00Z], 3.0, 0.0)])
      assert d.net == 3.0 and d.fees_other == 0.001
    end
  end

  defp and_in(a, b), do: abs(a - b) < 1.0e-9

  describe "NotionalDeposit" do
    test "defaults to the pilot capital, a change holds from its month on" do
      Application.put_env(:fluxtrader, :live_pilot, capital_usd: 1000.0)
      on_exit(fn -> Application.delete_env(:fluxtrader, :live_pilot) end)

      assert NotionalDeposit.for_month({2026, 11}) == 1000.0
      {:ok, _} = NotionalDeposit.put(1500, ~U[2026-12-15 10:00:00Z])
      {:ok, _} = NotionalDeposit.put(2000, ~U[2026-12-20 10:00:00Z])

      assert NotionalDeposit.for_month({2026, 11}) == 1000.0
      assert NotionalDeposit.for_month({2026, 12}) == 2000.0
      assert NotionalDeposit.for_month({2027, 3}) == 2000.0
      assert length(NotionalDeposit.history()) == 1
      assert {:error, _} = NotionalDeposit.put(0)
    end
  end

  describe "Stats.monthly/3" do
    test "bot from 11-01, manual from manual_since, % of that month's deposit" do
      d = fn owner, closed, net ->
        %{owner: owner, closed_at: closed, net: net, pnl: net, fees: 0.0, funding: 0.0}
      end

      deals = [
        d.(:bot, ~U[2026-10-31 23:00:00Z], 50.0),
        d.(:bot, ~U[2026-11-02 21:00:00Z], 10.0),
        d.(:manual, ~U[2026-11-05 20:00:00Z], 99.0),
        d.(:manual, ~U[2026-11-20 10:00:00Z], -25.0),
        d.(:bot, ~U[2026-12-02 10:00:00Z], 6.0)
      ]

      hist = [%{"from" => "2026-11", "usd" => 1000.0}, %{"from" => "2026-12", "usd" => 2000.0}]
      rows = Stats.monthly(deals, ~U[2026-12-10 00:00:00Z], hist)

      assert Enum.map(rows, &{&1.month, &1.owner, &1.deals, Float.round(&1.result_pct, 6)}) == [
               {"2026-12", :bot, 1, 0.3},
               {"2026-12", :manual, 0, 0.0},
               {"2026-11", :bot, 1, 1.0},
               {"2026-11", :manual, 1, -2.5}
             ]
    end
  end

  describe "LivePilot sizing" do
    test "notional and loss limits follow the deposit; unset deposit = env values" do
      Application.put_env(:fluxtrader, :live_pilot,
        capital_usd: 1000.0, notional_usd: 200.0, daily_loss_usd: 20.0, max_total_loss_usd: 200.0)

      on_exit(fn -> Application.delete_env(:fluxtrader, :live_pilot) end)

      cfg = LivePilot.scaled_config()
      assert {cfg[:notional_usd], cfg[:daily_loss_usd], cfg[:max_total_loss_usd]} == {200.0, 20.0, 200.0}

      {:ok, _} = NotionalDeposit.put(1500)
      cfg = LivePilot.scaled_config()
      assert {cfg[:notional_usd], cfg[:daily_loss_usd], cfg[:max_total_loss_usd]} == {300.0, 30.0, 300.0}
    end
  end

  describe "Sync.sync/1" do
    test "copies income and fills, attributes by the live arm's order ids, finds no mismatch" do
      now = System.system_time(:millisecond)
      t = fn h -> now - h * 3_600_000 end

      income = [
        %{"symbol" => "SOLUSDT", "incomeType" => "COMMISSION", "income" => "-0.1", "asset" => "USDT", "tranId" => 1, "tradeId" => "100", "time" => t.(30)},
        %{"symbol" => "SOLUSDT", "incomeType" => "COMMISSION", "income" => "-0.1", "asset" => "USDT", "tranId" => 2, "tradeId" => "101", "time" => t.(26)},
        %{"symbol" => "SOLUSDT", "incomeType" => "COMMISSION", "income" => "-0.1", "asset" => "USDT", "tranId" => 3, "tradeId" => "102", "time" => t.(2)},
        %{"symbol" => "", "incomeType" => "TRANSFER", "income" => "100", "asset" => "USDT", "tranId" => 4, "tradeId" => "", "time" => t.(40)}
      ]

      trades = [
        %{"symbol" => "SOLUSDT", "id" => 100, "orderId" => 555, "side" => "BUY", "qty" => "2.2", "price" => "90", "realizedPnl" => "0", "commission" => "0.1", "commissionAsset" => "USDT", "maker" => false, "time" => t.(30)},
        %{"symbol" => "SOLUSDT", "id" => 101, "orderId" => 556, "side" => "SELL", "qty" => "2.2", "price" => "91", "realizedPnl" => "2.2", "commission" => "0.1", "commissionAsset" => "USDT", "maker" => true, "time" => t.(26)},
        %{"symbol" => "SOLUSDT", "id" => 102, "orderId" => 900, "side" => "BUY", "qty" => "5.79", "price" => "86", "realizedPnl" => "0", "commission" => "0.1", "commissionAsset" => "USDT", "maker" => true, "time" => t.(2)}
      ]

      in_window = fn rows, p -> Enum.filter(rows, &(&1["time"] >= p[:startTime] and &1["time"] <= p[:endTime])) end

      get = fn
        "/fapi/v1/income", p -> {:ok, in_window.(income, p)}
        "/fapi/v1/userTrades", p -> {:ok, in_window.(trades, p)}
        "/fapi/v2/account", _ -> {:ok, %{"positions" => [%{"symbol" => "SOLUSDT", "positionAmt" => "5.79"}, %{"symbol" => "BTCUSDT", "positionAmt" => "0"}]}}
      end

      Repo.insert!(%PaperTrade{arm: "live", pair: "SOLUSDT", side: 1, size: 1.0, status: "closed",
        entry_ts: ~U[2026-11-09 00:00:00Z], exit_after_ts: ~U[2026-11-09 04:00:00Z], entry_price: 90.0,
        entry_order_id: 555, exit_order_id: 556})

      assert {:ok, []} = Sync.sync(get)
      # A second pass re-reads the overlap and inserts nothing new.
      assert {:ok, []} = Sync.sync(get)
      assert Repo.aggregate(Fill, :count) == 3
      assert Repo.aggregate(Income, :count) == 4

      [bot, manual] = Stats.deals()
      assert bot.owner == :bot and and_in(bot.net, 2.2 - 0.2)
      assert manual.owner == :manual and manual.closed_at == nil
    end

    test "a position the fills don't reach is a mismatch" do
      assert [%{symbol: "ADAUSDT", exchange: 2495.0, rebuilt: 1169.0}] =
               Sync.mismatches(%{"ADAUSDT" => 2495.0}, [
                 %{symbol: "ADAUSDT", qty: 1169.0, closed_at: nil}
               ])
    end
  end
end
