defmodule FluxTraderWeb.AccountLiveTest do
  @moduledoc "The account page renders empty, and setting the notional deposit re-sizes the pilot line."
  use FluxTraderWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  setup do
    Application.put_env(:fluxtrader, :live_pilot,
      capital_usd: 1000.0, notional_usd: 200.0, daily_loss_usd: 20.0, max_total_loss_usd: 200.0)

    on_exit(fn -> Application.delete_env(:fluxtrader, :live_pilot) end)
    :ok
  end

  test "empty account, then a new deposit", %{conn: conn} do
    {:ok, view, html} = live(conn, "/account")
    assert html =~ "Notional deposit"
    assert html =~ "$1000.00"
    assert html =~ "Sync worker not running"
    assert html =~ "$200.00</strong> a trade"

    html = view |> form("form[phx-submit=set_deposit]", %{"usd" => "1500"}) |> render_submit()
    assert html =~ "$1500.00"
    assert html =~ "$300.00</strong> a trade"
    assert html =~ "from #{FluxTrader.Account.NotionalDeposit.month_key(DateTime.utc_now())} $1500.00"
  end

  test "populated: a closed bot deal in this month's row, an open manual deal", %{conn: conn} do
    now = DateTime.utc_now()
    at = fn h -> DateTime.add(now, -h * 3600, :second) end
    stamp = NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)

    fill = fn id, order, side, qty, pnl, h, sym ->
      %{symbol: sym, trade_id: id, order_id: order, side: side, qty: qty, price: 1.0, realized_pnl: pnl,
        commission: 0.1, commission_asset: "USDT", maker: true, time: at.(h), inserted_at: stamp, updated_at: stamp}
    end

    FluxTrader.Repo.insert_all(FluxTrader.Account.Fill, [
      fill.(1, 555, "BUY", 2.2, 0.0, 3, "SOLUSDT"),
      fill.(2, 556, "SELL", 2.2, 10.2, 1, "SOLUSDT"),
      fill.(3, 900, "BUY", 2495.0, 0.0, 2, "ADAUSDT")
    ])

    FluxTrader.Repo.insert!(%FluxTrader.Trading.PaperTrade{arm: "live", pair: "SOLUSDT", side: 1, size: 1.0,
      status: "closed", entry_ts: DateTime.truncate(at.(3), :second), exit_after_ts: DateTime.truncate(at.(1), :second), entry_price: 90.0,
      entry_order_id: 555, exit_order_id: 556})

    {:ok, _view, html} = live(conn, "/account")
    assert html =~ "+10.00"
    assert html =~ "+1.00 %"
    assert html =~ "ADAUSDT"
    assert html =~ "2495"
  end
end
