defmodule FluxTrader.Data.Candles do
  @moduledoc """
  Query helpers for OHLCV candles.
  """
  import Ecto.Query
  alias FluxTrader.Data.Candle
  alias FluxTrader.Repo

  @doc """
  Latest candle per symbol for a given interval (default 1m).
  Returns a map of symbol => [candle_map] for dashboard display.
  """
  def latest_by_symbol(interval \\ "1m", symbols \\ nil) do
    symbols =
      symbols ||
        try do
          FluxTrader.Pairs.Selector.active_pairs()
        rescue
          _ ->
            Application.get_env(:fluxtrader, :trading, [])
            |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        catch
          :exit, _ ->
            Application.get_env(:fluxtrader, :trading, [])
            |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        end

    Enum.reduce(symbols, %{}, fn symbol, acc ->
      case latest(symbol, interval) do
        nil -> acc
        candle -> Map.put(acc, symbol, [to_display(candle)])
      end
    end)
  end

  def latest(symbol, interval \\ "1m") do
    from(c in Candle,
      where: c.symbol == ^symbol and c.interval == ^interval,
      order_by: [desc: c.open_time],
      limit: 1
    )
    |> Repo.one()
  end

  defp to_display(%Candle{} = c) do
    %{
      symbol: c.symbol,
      interval: c.interval,
      open_time: c.open_time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume,
      close_time: c.close_time
    }
  end
end
