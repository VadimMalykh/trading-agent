defmodule FluxTrader.Binance.Trade.Rest do
  @moduledoc """
  `Binance.Trade` over signed HTTPS — the only module that can place a real order.

  ## Two hosts, on purpose

  Signed calls go to `Binance.Client.trade_url/0`, which `BINANCE_TESTNET=true` points at
  `https://demo-fapi.binance.com`. Market data stays on `fapi.binance.com` regardless
  (see `Binance.Trade`'s moduledoc). So a testnet run trades testnet positions off real
  prices, which is the only combination that tells you anything about the order path.

  ## What a response looks like

  Binance answers a `MARKET` order placed with `newOrderRespType=RESULT` with the fill
  already in it — `status`, `avgPrice`, `executedQty` — so the common case needs no second
  round trip. `Trading.ExchangeOrders` still reconciles against `get_order/2` whenever the
  status is not terminal, because "usually filled by the time it answers" is not a ledger.

  Errors come back as `{:error, {status, %{"code" => c, "msg" => m}}}` so callers can match
  on Binance's numeric codes (`-2022` ReduceOnly rejected, `-2019` margin insufficient,
  `-4164` below min notional, `-1111` precision).
  """
  @behaviour FluxTrader.Binance.Trade

  alias FluxTrader.Binance.Client

  @impl true
  def exchange_info, do: Client.signed_get("/fapi/v1/exchangeInfo", [], auth: :none)

  @impl true
  def set_leverage(symbol, leverage),
    do: Client.signed_post("/fapi/v1/leverage", symbol: symbol, leverage: leverage)

  @impl true
  def place_order(params), do: Client.signed_post("/fapi/v1/order", params)

  @impl true
  def get_order(symbol, order_id),
    do: Client.signed_get("/fapi/v1/order", symbol: symbol, orderId: order_id)

  @impl true
  def cancel_all_open_orders(symbol),
    do: Client.signed_delete("/fapi/v1/allOpenOrders", symbol: symbol)

  @impl true
  def position_risk(symbol), do: Client.signed_get("/fapi/v2/positionRisk", symbol: symbol)

  @impl true
  def mark_price(symbol),
    do: Client.signed_get("/fapi/v1/premiumIndex", [symbol: symbol], auth: :none)

  @impl true
  def commission_rate(symbol),
    do: Client.signed_get("/fapi/v1/commissionRate", symbol: symbol)

  @impl true
  def listen_key, do: Client.signed_post("/fapi/v1/listenKey", [], auth: :key_only)

  @impl true
  def keepalive_listen_key, do: Client.signed_put("/fapi/v1/listenKey", [], auth: :key_only)
end
