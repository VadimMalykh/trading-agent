defmodule FluxTrader.Binance.Client do
  @moduledoc """
  HTTP client for Binance Futures public REST API (no API key required for market data).
  """

  @base_url "https://fapi.binance.com"

  defp finch_name, do: FluxTrader.Finch

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
  # (docs/DATA_COLLECTION_AUDIT.md). Minimum `period` is "5m".
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
  opposite position.
  """
  def place_order(order_params) do
    body =
      [
        symbol: order_params.symbol,
        side: order_params.side,
        type: "MARKET",
        quantity: order_params.quantity
      ]
      |> maybe_put(:reduceOnly, if(Map.get(order_params, :reduce_only), do: "true"))
      |> URI.encode_query()

    post("/fapi/v1/order", body)
  end

  defp maybe_put(params, _key, nil), do: params
  defp maybe_put(params, key, value), do: Keyword.put(params, key, value)

  defp get(path) do
    url = if String.starts_with?(path, "http"), do: path, else: "#{@base_url}#{path}"

    case Finch.build(:get, url) |> Finch.request(finch_name(), receive_timeout: 30_000) do
      {:ok, %{status: 200, body: body}} ->
        {:ok, decode(body)}

      {:ok, %{status: status, body: body}} ->
        {:error, {status, decode(body)}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp post(path, body) do
    url = "#{@base_url}#{path}"

    case Finch.build(:post, url, [{"content-type", "application/x-www-form-urlencoded"}], body)
         |> Finch.request(finch_name(), receive_timeout: 30_000) do
      {:ok, %{status: 200, body: resp_body}} ->
        {:ok, decode(resp_body)}

      {:ok, %{status: status, body: resp_body}} ->
        {:error, {status, decode(resp_body)}}

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
