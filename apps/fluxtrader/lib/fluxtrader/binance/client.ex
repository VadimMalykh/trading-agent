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

  def order_book(symbol, limit \\ 20) do
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

  def force_orders(symbol, opts \\ []) do
    limit = Keyword.get(opts, :limit, 50)
    params = URI.encode_query(symbol: symbol, limit: limit)
    get("/fapi/v1/allForceOrders?#{params}")
  end

  def place_order(order_params) do
    body =
      URI.encode_query(
        symbol: order_params.symbol,
        side: order_params.side,
        type: "MARKET",
        quantity: order_params.quantity
      )

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
