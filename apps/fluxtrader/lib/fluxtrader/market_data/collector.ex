defmodule FluxTrader.MarketData.Collector do
  @moduledoc """
  Polls Binance Futures public REST for M1 market data and persists to Postgres.
  No API keys required.
  """
  use GenServer
  require Logger

  alias FluxTrader.Binance.Client
  alias FluxTrader.MarketData.{BookFeatures, MarketTrade, OrderbookSnapshot, FundingRate, OpenInterest, Liquidation}
  alias FluxTrader.Data.Candle
  alias FluxTrader.Repo

  @book_interval_ms 5_000
  @trade_interval_ms 5_000
  @slow_interval_ms 60_000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(_opts) do
    pairs = pairs()

    state = %{
      pairs: pairs,
      last_trade_ids: %{}
    }

    Phoenix.PubSub.subscribe(FluxTrader.PubSub, "settings:whitelist")

    # Backfill history once so M1 training has enough samples without waiting hours
    Process.send_after(self(), :backfill_history, 500)
    Process.send_after(self(), :poll_book, 1_000)
    Process.send_after(self(), :poll_trades, 2_000)
    Process.send_after(self(), :poll_slow, 3_000)
    Process.send_after(self(), :poll_candles, 4_000)

    Logger.info("MarketData.Collector started for #{inspect(pairs)}")
    {:ok, state}
  end

  def handle_info({:whitelist, pairs}, state) do
    Logger.info("Collector whitelist updated: #{inspect(pairs)}")
    # Backfill new pairs shortly
    Process.send_after(self(), :backfill_history, 1_000)
    {:noreply, %{state | pairs: pairs}}
  end

  def handle_info(:backfill_history, state) do
    state = sync_pairs(state)
    Logger.info("Backfilling historical klines for M1...")

    Enum.each(state.pairs, fn pair ->
      try do
        backfill_candles(pair, "1m", 500)
        backfill_candles(pair, "5m", 500)
        backfill_candles(pair, "15m", 500)
        backfill_candles(pair, "1h", 500)
        collect_book(pair)
        collect_funding(pair)
        collect_open_interest(pair)
      rescue
        e ->
          Logger.error("Backfill crashed for #{pair}: #{Exception.message(e)}")
      end
    end)

    Logger.info("Historical backfill complete")
    {:noreply, state}
  end

  @impl true
  def handle_info(:poll_book, state) do
    state = sync_pairs(state)
    Enum.each(state.pairs, &collect_book/1)
    Process.send_after(self(), :poll_book, @book_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_trades, state) do
    state = sync_pairs(state)

    state =
      Enum.reduce(state.pairs, state, fn pair, acc ->
        case collect_trades(pair, Map.get(acc.last_trade_ids, pair)) do
          {:ok, last_id} ->
            %{acc | last_trade_ids: Map.put(acc.last_trade_ids, pair, last_id)}

          :ok ->
            acc

          {:error, _} ->
            acc
        end
      end)

    Process.send_after(self(), :poll_trades, @trade_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_slow, state) do
    state = sync_pairs(state)

    Enum.each(state.pairs, fn pair ->
      collect_funding(pair)
      collect_open_interest(pair)
      collect_liquidations(pair)
    end)

    Process.send_after(self(), :poll_slow, @slow_interval_ms)
    {:noreply, state}
  end

  def handle_info(:poll_candles, state) do
    state = sync_pairs(state)

    Enum.each(state.pairs, fn pair ->
      try do
        collect_candles(pair, "1m")
        collect_candles(pair, "5m")
        collect_candles(pair, "15m")
        collect_candles(pair, "1h")
      rescue
        e -> Logger.warning("poll_candles crashed for #{pair}: #{Exception.message(e)}")
      catch
        :exit, reason -> Logger.warning("poll_candles exit for #{pair}: #{inspect(reason)}")
      end
    end)

    Process.send_after(self(), :poll_candles, @slow_interval_ms)
    {:noreply, state}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp sync_pairs(state) do
    %{state | pairs: pairs()}
  end

  defp pairs do
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
  end

  defp collect_book(symbol) do
    case Client.order_book(symbol, 20) do
      {:ok, depth} ->
        case BookFeatures.from_depth(symbol, depth) do
          {:ok, features} ->
            %OrderbookSnapshot{}
            |> OrderbookSnapshot.changeset(features)
            |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

            Phoenix.PubSub.broadcast(FluxTrader.PubSub, "market:book", {:book, features})

          {:error, reason} ->
            Logger.debug("Book features skip #{symbol}: #{inspect(reason)}")
        end

      {:error, reason} ->
        Logger.warning("Book poll failed #{symbol}: #{inspect(reason)}")
    end
  end

  defp collect_trades(symbol, last_id) do
    opts = [limit: 200]

    case Client.agg_trades(symbol, opts) do
      {:ok, trades} when is_list(trades) and trades != [] ->
        trades =
          if last_id do
            Enum.filter(trades, fn t -> Map.get(t, "a", 0) > last_id end)
          else
            trades
          end

        if trades == [] do
          :ok
        else
          window = aggregate_trades(symbol, trades)
          max_id = trades |> Enum.map(&Map.get(&1, "a", 0)) |> Enum.max()

          %MarketTrade{}
          |> MarketTrade.changeset(window)
          |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :window_start])

          {:ok, max_id}
        end

      {:ok, _} ->
        :ok

      {:error, reason} ->
        Logger.warning("Trades poll failed #{symbol}: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp aggregate_trades(symbol, trades) do
    prices = Enum.map(trades, &to_f(Map.get(&1, "p")))
    qtys = Enum.map(trades, &to_f(Map.get(&1, "q")))

    {buy_vol, sell_vol} =
      Enum.zip(trades, qtys)
      |> Enum.reduce({0.0, 0.0}, fn {t, q}, {b, s} ->
        # m = true means buyer is market maker => seller aggressor
        if Map.get(t, "m") == true, do: {b, s + q}, else: {b + q, s}
      end)

    volume = Enum.sum(qtys)
    notional = Enum.zip(prices, qtys) |> Enum.reduce(0.0, fn {p, q}, acc -> acc + p * q end)
    vwap = if volume > 0, do: notional / volume, else: List.last(prices) || 0.0
    ts = trades |> List.last() |> Map.get("T") |> ms_to_dt()

    %{
      symbol: symbol,
      window_start: floor_to_5s(ts),
      trade_count: length(trades),
      volume: volume,
      buy_volume: buy_vol,
      sell_volume: sell_vol,
      vwap: vwap,
      high: Enum.max(prices),
      low: Enum.min(prices)
    }
  end

  defp collect_funding(symbol) do
    case Client.premium_index(symbol) do
      {:ok, data} when is_map(data) ->
        attrs = %{
          symbol: symbol,
          ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
          mark_price: to_f(Map.get(data, "markPrice")),
          index_price: to_f(Map.get(data, "indexPrice")),
          last_funding_rate: to_f(Map.get(data, "lastFundingRate")),
          next_funding_time: ms_to_dt(Map.get(data, "nextFundingTime"))
        }

        %FundingRate{}
        |> FundingRate.changeset(attrs)
        |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

      {:error, reason} ->
        Logger.warning("Funding poll failed #{symbol}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp collect_open_interest(symbol) do
    case Client.open_interest(symbol) do
      {:ok, data} when is_map(data) ->
        attrs = %{
          symbol: symbol,
          ts: DateTime.utc_now() |> DateTime.truncate(:microsecond),
          open_interest: to_f(Map.get(data, "openInterest"))
        }

        %OpenInterest{}
        |> OpenInterest.changeset(attrs)
        |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :ts])

      {:error, reason} ->
        Logger.warning("OI poll failed #{symbol}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp collect_liquidations(symbol) do
    case Client.force_orders(symbol, limit: 20) do
      {:ok, orders} when is_list(orders) ->
        Enum.each(orders, fn o ->
          attrs = %{
            symbol: Map.get(o, "symbol", symbol),
            ts: ms_to_dt(Map.get(o, "time") || Map.get(o, "updateTime")),
            side: Map.get(o, "side"),
            price: to_f(Map.get(o, "price") || Map.get(o, "averagePrice")),
            quantity: to_f(Map.get(o, "origQty") || Map.get(o, "executedQty")),
            order_id: to_string(Map.get(o, "orderId", ""))
          }

          if attrs.ts do
            %Liquidation{}
            |> Liquidation.changeset(attrs)
            |> Repo.insert()
            |> case do
              {:ok, _} -> :ok
              {:error, _} -> :ok
            end
          end
        end)

      {:error, {status, _}} when status in [401, 403, 404] ->
        # Endpoint may require auth on some deployments; skip quietly
        :ok

      {:error, reason} ->
        Logger.debug("Liquidations poll #{symbol}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp collect_candles(symbol, interval) do
    case Client.klines(symbol, interval, limit: 5) do
      {:ok, rows} when is_list(rows) ->
        Enum.each(rows, &insert_candle(symbol, interval, &1, broadcast: interval == "1m"))

      {:error, reason} ->
        Logger.warning("Candle poll failed #{symbol}/#{interval}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp backfill_candles(symbol, interval, limit) do
    case Client.klines(symbol, interval, limit: limit) do
      {:ok, rows} when is_list(rows) ->
        Enum.each(rows, &insert_candle(symbol, interval, &1, broadcast: false))
        Logger.info("Backfilled #{length(rows)} #{interval} candles for #{symbol}")

      {:error, reason} ->
        Logger.warning("Backfill failed #{symbol}/#{interval}: #{inspect(reason)}")

      _ ->
        :ok
    end
  end

  defp insert_candle(symbol, interval, kline, opts) do
    candle = parse_kline(symbol, interval, kline)

    try do
      %Candle{}
      |> Candle.changeset(candle)
      |> Repo.insert(on_conflict: :nothing, conflict_target: [:symbol, :interval, :open_time])
    rescue
      e -> Logger.warning("candle insert failed #{symbol}/#{interval}: #{Exception.message(e)}")
    catch
      :exit, reason -> Logger.warning("candle insert exit #{symbol}/#{interval}: #{inspect(reason)}")
    end

    if Keyword.get(opts, :broadcast, false) do
      Phoenix.PubSub.broadcast(FluxTrader.PubSub, "candles:live", {:new_candle, candle})
    end
  end

  defp parse_kline(symbol, interval, kline) when is_list(kline) do
    %{
      symbol: symbol,
      interval: interval,
      open_time: ms_to_dt(Enum.at(kline, 0)),
      open: to_f(Enum.at(kline, 1)),
      high: to_f(Enum.at(kline, 2)),
      low: to_f(Enum.at(kline, 3)),
      close: to_f(Enum.at(kline, 4)),
      volume: to_f(Enum.at(kline, 5)),
      close_time: ms_to_dt(Enum.at(kline, 6))
    }
  end

  defp floor_to_5s(%DateTime{} = dt) do
    unix = DateTime.to_unix(dt)
    floored = div(unix, 5) * 5
    DateTime.from_unix!(floored) |> DateTime.truncate(:microsecond)
  end

  defp floor_to_5s(_), do: DateTime.utc_now() |> DateTime.truncate(:microsecond)

  defp ms_to_dt(nil), do: nil
  defp ms_to_dt(ms) when is_integer(ms), do: DateTime.from_unix!(ms, :millisecond) |> DateTime.truncate(:microsecond)
  defp ms_to_dt(_), do: nil

  defp to_f(nil), do: 0.0
  defp to_f(v) when is_float(v), do: v
  defp to_f(v) when is_integer(v), do: v * 1.0

  defp to_f(v) when is_binary(v) do
    case Float.parse(v) do
      {f, _} -> f
      :error -> 0.0
    end
  end

  defp to_f(_), do: 0.0
end
