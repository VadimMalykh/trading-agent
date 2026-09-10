defmodule FluxTrader.Binance.Filters do
  @moduledoc """
  The per-symbol rounding rules an order must satisfy before Binance will look at it.

  `RiskManager` sizes a position as `capital * pct / price * leverage`, which for BTC at
  $100k is something like `0.00833333 BTC` — a number the exchange rejects outright
  (`-1111 Precision is over the maximum defined for this asset`). Every real order therefore
  passes through here first:

    * **quantity** is rounded *down* to the `LOT_SIZE` step (never up — rounding up is how a
      position ends larger than the risk manager approved);
    * **prices** (the stop and target) are rounded to the `PRICE_FILTER` tick;
    * **notional** is checked against `MIN_NOTIONAL` — on USDⓈ-M that is 100 USDT for most
      symbols, and an order below it is refused *here*, with a named reason, rather than
      sent and bounced with `-4164`.

  Built from `/fapi/v1/exchangeInfo`, which the testnet serves separately from production,
  so a testnet run rounds to testnet's filters.
  """

  @type t :: %{
          step: float(),
          tick: float(),
          min_notional: float(),
          qty_precision: non_neg_integer(),
          price_precision: non_neg_integer()
        }

  @doc "Parse `exchangeInfo` into `%{symbol => filters}`. Pure."
  @spec from_exchange_info(map()) :: %{String.t() => t()}
  def from_exchange_info(%{"symbols" => symbols}) do
    Map.new(symbols, fn s ->
      filters = Map.new(s["filters"] || [], &{&1["filterType"], &1})

      {s["symbol"],
       %{
         step: to_f(get_in(filters, ["LOT_SIZE", "stepSize"]), 0.001),
         tick: to_f(get_in(filters, ["PRICE_FILTER", "tickSize"]), 0.01),
         min_notional: to_f(get_in(filters, ["MIN_NOTIONAL", "notional"]), 0.0),
         qty_precision: s["quantityPrecision"] || 3,
         price_precision: s["pricePrecision"] || 2
       }}
    end)
  end

  @doc "Quantity rounded DOWN to the lot step, as a float with the symbol's precision."
  def round_qty(%{step: step, qty_precision: prec}, qty) when is_number(qty) do
    Float.floor(qty / step) * step |> Float.round(prec)
  end

  @doc "Price rounded to the nearest tick, with the symbol's precision."
  def round_price(%{tick: tick, price_precision: prec}, price) when is_number(price) do
    Float.round(price / tick) * tick |> Float.round(prec)
  end

  @doc """
  Round a requested quantity and refuse it if the resulting order is too small.

  Returns `{:ok, qty}` or `{:error, :below_min_notional}` / `{:error, :zero_quantity}`.
  """
  def sized_qty(filters, qty, price) do
    q = round_qty(filters, qty)

    cond do
      q <= 0.0 -> {:error, :zero_quantity}
      q * price < filters.min_notional -> {:error, :below_min_notional}
      true -> {:ok, q}
    end
  end

  defp to_f(nil, default), do: default
  defp to_f(v, _default) when is_number(v), do: v * 1.0

  defp to_f(v, default) when is_binary(v) do
    case Float.parse(v) do
      {f, _} -> f
      :error -> default
    end
  end
end
