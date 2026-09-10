defmodule FluxTrader.Binance.Trade do
  @moduledoc """
  The exchange's private surface, as a behaviour — the calls that need an API key.

  Every function `Trading.ExchangeOrders` uses to open, brake, close and reconcile a real
  position goes through this behaviour, so the whole order path can be exercised against
  `FluxTrader.Binance.Trade.Fake` in tests and against `Trade.Rest` on the testnet, with the
  production code between them unchanged. The implementation in force is
  `Application.get_env(:fluxtrader, :trade_client, FluxTrader.Binance.Trade.Rest)`.

  Market data (`Binance.Client.klines/3` and friends) is **not** here: it needs no key and
  it must keep reading the production exchange even when trading is pointed at the testnet,
  or the collector would start storing testnet prices as history.
  """

  @type result :: {:ok, map() | list()} | {:error, term()}

  @doc "GET /fapi/v1/exchangeInfo from the trading host (testnet has its own filters)."
  @callback exchange_info() :: result

  @doc "POST /fapi/v1/leverage — set the symbol's leverage. Idempotent."
  @callback set_leverage(symbol :: String.t(), leverage :: pos_integer()) :: result

  @doc """
  POST /fapi/v1/order with the given parameters (`symbol`, `side`, `type`, `quantity`,
  `reduceOnly`, `stopPrice`, `closePosition`, `workingType`, `newOrderRespType`, ...).
  """
  @callback place_order(params :: keyword()) :: result

  @doc "GET /fapi/v1/order — the order's current status, fill price and filled quantity."
  @callback get_order(symbol :: String.t(), order_id :: integer()) :: result

  @doc "DELETE /fapi/v1/allOpenOrders — every resting order on the symbol, brakes included."
  @callback cancel_all_open_orders(symbol :: String.t()) :: result

  @doc "GET /fapi/v2/positionRisk — the exchange's own view of the position on a symbol."
  @callback position_risk(symbol :: String.t()) :: result

  @doc "GET /fapi/v1/commissionRate — the account's real maker/taker fee for a symbol."
  @callback commission_rate(symbol :: String.t()) :: result

  @doc "POST /fapi/v1/listenKey — open a user-data stream key. API key only, unsigned."
  @callback listen_key() :: result

  @doc "PUT /fapi/v1/listenKey — keep the key alive; Binance expires it after 60 minutes."
  @callback keepalive_listen_key() :: result

  @doc "The implementation in force."
  def impl, do: Application.get_env(:fluxtrader, :trade_client, FluxTrader.Binance.Trade.Rest)
end
