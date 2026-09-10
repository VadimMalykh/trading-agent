defmodule FluxTrader.Binance.Client do
  @moduledoc """
  HTTP client for the Binance USDⓈ-M Futures REST API.

  Two kinds of call live here and they go to **different hosts**:

    * **Market data** (`klines/3`, `order_book/2`, ...) — unsigned, always against
      `fapi.binance.com`. The collector's history must never come from the testnet.
    * **Signed / keyed calls** (`signed_get/3`, `signed_post/3`, ...) — against
      `trade_url/0`, which `BINANCE_TESTNET=true` points at `demo-fapi.binance.com`.
      The signing arithmetic is `Binance.Auth`; the endpoints are `Binance.Trade.Rest`.

  Until 2026-09-10 `post/2` sent neither the `X-MBX-APIKEY` header nor a signature, so
  `place_order/1` returned 401 on every call. It now signs, and it is the only order path.
  """

  alias FluxTrader.Binance.Auth

  @market_url "https://fapi.binance.com"

  defp finch_name, do: FluxTrader.Finch

  @doc "Where signed calls go. Production unless `BINANCE_TESTNET=true`."
  def trade_url, do: binance_config(:trade_url) || @market_url

  @doc "The user-data stream host, matching `trade_url/0`'s environment."
  def user_stream_host, do: binance_config(:user_stream_host) || "fstream.binance.com"

  @doc "Whether signed calls are pointed at the testnet."
  def testnet?, do: binance_config(:testnet) == true

  @doc "`{key, secret}` or `nil` when either is missing — credentials are never half-present."
  def credentials do
    key = binance_config(:api_key)
    secret = binance_config(:api_secret)
    if blank?(key) or blank?(secret), do: nil, else: {key, secret}
  end

  def credentials?, do: credentials() != nil

  defp binance_config(k), do: Application.get_env(:fluxtrader, :binance, []) |> Keyword.get(k)

  defp blank?(nil), do: true
  defp blank?(""), do: true
  defp blank?(_), do: false

  def exchange_info do
    get("/fapi/v1/exchangeInfo")
  end

  def klines(symbol, interval, opts \\ []) do
    limit = Keyword.get(opts, :limit, 500)
    start_time = Keyword.get(opts, :start_time)
    end_time = Keyword.get(opts, :end_time)

    params =
      [symbol: symbol, interval: interval, limit: limit]
      |> maybe_put(:startTime, start_time)
      |> maybe_put(:endTime, end_time)

    get("/fapi/v1/klines?#{URI.encode_query(params)}")
  end

  def order_book(symbol, limit \\ 100) do
    params = URI.encode_query(symbol: symbol, limit: limit)
    get("/fapi/v1/depth?#{params}")
  end

  def agg_trades(symbol, opts \\ []) do
    limit = Keyword.get(opts, :limit, 500)
    start_time = Keyword.get(opts, :start_time)
    end_time = Keyword.get(opts, :end_time)

    params =
      [symbol: symbol, limit: limit]
      |> maybe_put(:startTime, start_time)
      |> maybe_put(:endTime, end_time)

    get("/fapi/v1/aggTrades?#{URI.encode_query(params)}")
  end

  def premium_index(symbol) do
    params = URI.encode_query(symbol: symbol)
    get("/fapi/v1/premiumIndex?#{params}")
  end

  def funding_rate(symbol) do
    premium_index(symbol)
  end

  def funding_rate_history(symbol, opts \\ []) do
    limit = Keyword.get(opts, :limit, 100)
    params = URI.encode_query(symbol: symbol, limit: limit)
    get("/fapi/v1/fundingRate?#{params}")
  end

  def open_interest(symbol) do
    params = URI.encode_query(symbol: symbol)
    get("/fapi/v1/openInterest?#{params}")
  end

  # --- Positioning / sentiment ratios (B4.2) ---------------------------------
  #
  # `/futures/data/*` endpoints, NOT `/fapi/v1/*`. The exchange retains these
  # series for only ~30 days, so history beyond that exists only if we stored it
  # (docs/archive/DATA_COLLECTION_AUDIT.md). Minimum `period` is "5m".
  #
  # All three return a LIST of maps, oldest-first, each with a "timestamp" (ms).
  # `start_time`/`end_time` page the ~30-day window; `limit` maxes out at 500.

  @doc "Top traders' long/short ACCOUNT ratio. Rows: longShortRatio/longAccount/shortAccount."
  def top_long_short_account_ratio(symbol, opts \\ []) do
    futures_data("topLongShortAccountRatio", symbol, opts)
  end

  @doc "All accounts' long/short ratio. Same row shape as top_long_short_account_ratio/2."
  def global_long_short_account_ratio(symbol, opts \\ []) do
    futures_data("globalLongShortAccountRatio", symbol, opts)
  end

  @doc "Taker (aggressor) buy/sell volume ratio. Rows: buySellRatio/buyVol/sellVol."
  def taker_long_short_ratio(symbol, opts \\ []) do
    futures_data("takerlongshortRatio", symbol, opts)
  end

  defp futures_data(endpoint, symbol, opts) do
    params =
      [symbol: symbol, period: Keyword.get(opts, :period, "5m"), limit: Keyword.get(opts, :limit, 30)]
      |> maybe_put(:startTime, Keyword.get(opts, :start_time))
      |> maybe_put(:endTime, Keyword.get(opts, :end_time))

    get("/futures/data/#{endpoint}?#{URI.encode_query(params)}")
  end

  # NOTE: Binance's REST liquidation endpoint (/fapi/v1/allForceOrders) is
  # auth-gated and unusable for public market-wide data. Liquidations are
  # collected in real time via the WebSocket !forceOrder@arr stream in
  # FluxTrader.Binance.WebSocket. There is no historical backfill.

  @doc """
  Place a MARKET order — i.e. cross the spread.

  There is no limit-order variant on purpose. M3-4 measured resting against crossing and
  found the maker arm's apparent saving to be a fee-rebate accounting gain that adverse
  selection reverses in 16 of 16 cells (`docs/M3_4_RESULTS.md` §3), so the executor crosses.

  `reduce_only: true` marks a closing order, which Binance then refuses to let flip into an
  opposite position. `newOrderRespType=RESULT` asks for the fill in the response.

  Kept for callers that want the raw call; `Trading.ExchangeOrders` is the path that also
  rounds, brakes and reconciles, and it is what the executor uses.
  """
  def place_order(order_params) do
    signed_post(
      "/fapi/v1/order",
      [
        symbol: order_params.symbol,
        side: order_params.side,
        type: "MARKET",
        quantity: order_params.quantity,
        newOrderRespType: "RESULT"
      ]
      |> maybe_put(:reduceOnly, if(Map.get(order_params, :reduce_only), do: "true"))
    )
  end

  # --- Signed / keyed calls -----------------------------------------------------------
  #
  # `auth:` selects how much of the credential travels: `:signed` (default) adds the key
  # header AND the HMAC payload; `:key_only` adds the header alone (the listenKey endpoints);
  # `:none` sends a plain request to the trading host (exchangeInfo, which testnet serves
  # separately). Missing credentials are an error, not a silent unsigned request — that is
  # exactly the failure the old `post/2` had.

  def signed_get(path, params, opts \\ []), do: signed_request(:get, path, params, opts)
  def signed_post(path, params, opts \\ []), do: signed_request(:post, path, params, opts)
  def signed_put(path, params, opts \\ []), do: signed_request(:put, path, params, opts)
  def signed_delete(path, params, opts \\ []), do: signed_request(:delete, path, params, opts)

  defp signed_request(method, path, params, opts) do
    auth = Keyword.get(opts, :auth, :signed)

    with {:ok, key, payload} <- build_payload(auth, params) do
      headers = if key, do: [{"X-MBX-APIKEY", key}], else: []

      {url, body, headers} =
        case method do
          m when m in [:post, :put] ->
            {trade_url() <> path, payload,
             [{"content-type", "application/x-www-form-urlencoded"} | headers]}

          _ ->
            {trade_url() <> path <> if(payload == "", do: "", else: "?" <> payload), nil,
             headers}
        end

      Finch.build(method, url, headers, body)
      |> Finch.request(finch_name(), receive_timeout: 15_000)
      |> handle_response()
    end
  end

  defp build_payload(:none, params), do: {:ok, nil, URI.encode_query(params)}

  defp build_payload(auth, params) do
    case credentials() do
      nil ->
        {:error, :missing_credentials}

      {key, secret} ->
        payload =
          case auth do
            :key_only -> URI.encode_query(params)
            :signed -> Auth.signed_payload(params, secret)
          end

        {:ok, key, payload}
    end
  end

  defp handle_response({:ok, %{status: 200, body: body}}), do: {:ok, decode(body)}
  defp handle_response({:ok, %{status: status, body: body}}), do: {:error, {status, decode(body)}}
  defp handle_response({:error, reason}), do: {:error, reason}

  defp maybe_put(params, _key, nil), do: params
  defp maybe_put(params, key, value), do: Keyword.put(params, key, value)

  defp get(path) do
    url = if String.starts_with?(path, "http"), do: path, else: "#{@market_url}#{path}"

    case Finch.build(:get, url) |> Finch.request(finch_name(), receive_timeout: 30_000) do
      {:ok, %{status: 200, body: body}} ->
        {:ok, decode(body)}

      {:ok, %{status: status, body: body}} ->
        {:error, {status, decode(body)}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp decode(body) when is_binary(body) do
    case Jason.decode(body) do
      {:ok, parsed} -> parsed
      {:error, _} -> body
    end
  end

  defp decode(body), do: body
end
