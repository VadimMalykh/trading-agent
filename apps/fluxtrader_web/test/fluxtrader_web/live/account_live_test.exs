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
end
